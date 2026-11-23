import json
import threading
import time
from typing import Callable, Optional
from urllib.parse import quote

import requests
import websocket

from chatbridge.common.logger import ChatBridgeLogger
from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl import utils
from chatbridge.impl.milky.config import MilkyConfig
from chatbridge.impl.milky.segments import make_text_segment, segment_text, segments_to_text, split_segments
from chatbridge.impl.tis.protocol import OnlineQueryResult, StatsQueryResult

ConfigFile = 'ChatBridge_Milky.json'
milky_bot: Optional['MilkyBot'] = None
chatClient: Optional['MilkyChatBridgeClient'] = None

MilkyHelpMessage = '''
直接发送消息即可转发到 Minecraft 服务器
!!help: 显示本条帮助信息
!!ping: pong!!
!!online [客户端]: 显示在线列表
!!stats <类别> <内容> [<-bot>]: 查询统计信息 <类别>.<内容> 的排名
'''.strip()
StatsHelpMessage = '''
`!!stats rank <类别> <内容> [<-bot>] [<-all>]`
添加`-bot`显示包含bot的排名（bot过滤逻辑挺简陋的）
添加`-all`显示所有玩家的排名，刷屏预警
`<类别>`: `killed`, `killed_by`, `dropped`, `picked_up`, `used`, `mined`, `broken`, `crafted`, `custom`
更多详情见：[统计信息wiki](https://zh.minecraft.wiki/w/%E7%BB%9F%E8%AE%A1%E4%BF%A1%E6%81%AF)
例子:
`!!stats rank used diamond_pickaxe`
`!!stats rank custom time_since_rest -bot`
'''.strip()


class MilkyBot(websocket.WebSocketApp):
	def __init__(self, config: MilkyConfig):
		self.config = config
		self.logger = ChatBridgeLogger('Bot', file_handler=chatClient.logger.file_handler)
		self._send_lock = threading.Lock()
		target_group = self._as_int(config.react_group_id)
		if target_group is None or target_group <= 0:
			raise ValueError('react_group_id must be a positive QQ group id, got {!r}'.format(config.react_group_id))
		self.logger.info('Reacting to messages from group {}'.format(target_group))
		url = 'ws://{}:{}/event'.format(config.milky_address, config.milky_port)
		self.logger.info('Connecting to {}'.format(url))
		if config.milky_access_token:
			url += '?access_token={}'.format(quote(config.milky_access_token, safe=''))
		# noinspection PyTypeChecker
		super().__init__(
			url,
			on_open=self.on_open,
			on_message=self.on_message,
			on_close=self.on_close,
			on_error=self.on_error,
		)

	def start(self):
		while True:
			try:
				# Some Milky implementations do not answer WebSocket ping frames.
				# Disable the client-side ping to avoid being disconnected by a
				# false ping timeout, and reconnect whenever the connection ends.
				self.run_forever()
			except KeyboardInterrupt:
				raise
			except Exception:
				self.logger.exception('Milky event connection failed')
			self.logger.warning('Milky event connection closed, reconnecting in 5 seconds')
			time.sleep(5)

	def on_open(self, _):
		self.logger.info('Milky event connection opened')

	def on_error(self, _, error):
		self.logger.error('Milky event connection error: {}'.format(error))

	def on_close(self, _, close_status_code, close_msg):
		self.logger.info('Close connection ({}: {})'.format(close_status_code, close_msg))

	def on_message(self, _, message: str):
		try:
			if chatClient is None:
				return
			event = json.loads(message)
			if event.get('event_type') != 'message_receive':
				return
			data = event.get('data') or {}
			message_scene = data.get('message_scene')
			if message_scene is not None and message_scene != 'group':
				return
			if message_scene is None and not (data.get('group') or data.get('group_member')):
				return
			if data.get('sender_id') == event.get('self_id'):
				return

			target_group = self._as_int(self.config.react_group_id)
			group_ids = self._get_group_ids(data)
			if target_group not in group_ids:
				self.logger.info('Ignoring group message from {} (target group {})'.format(
					', '.join(str(group_id) for group_id in sorted(group_ids)) or 'unknown', target_group
				))
				return
			self._on_group_message(data)
		except:
			self.logger.exception('Error in on_message()')

	@staticmethod
	def _as_int(value) -> Optional[int]:
		if value is None:
			return None
		try:
			return int(value)
		except (TypeError, ValueError):
			return None

	def _get_group_ids(self, data: dict) -> set:
		# Different implementations may put the group id in different fields.
		# LLBot's `peer_id` is not guaranteed to be the public group number, so
		# also accept the group entity's `group_id`.
		values = [data.get('peer_id')]
		for key in ('group', 'group_member'):
			value = data.get(key)
			if isinstance(value, dict):
				values.append(value.get('group_id'))
		group_ids = {self._as_int(value) for value in values}
		group_ids.discard(None)
		return group_ids

	def _on_group_message(self, data: dict):
		segments = data.get('segments') or []
		self.logger.info('QQ chat message: {}'.format(segments))

		command_text = segment_text(segments).strip()
		args = command_text.split()

		if len(args) == 1 and args[0] == '!!help':
			self.logger.info('!!help command triggered')
			self.send_text(MilkyHelpMessage)

		if len(args) == 1 and args[0] == '!!ping':
			self.logger.info('!!ping command triggered')
			self.send_text('pong!!')

		sender = self._get_sender_name(data)
		text = segments_to_text(segments, image_view=self.config.image_view)
		if text != '':
			chatClient.broadcast_chat(text, author=sender)

		if len(args) >= 1 and args[0] in ('!!online', 'online', 'on'):
			self._on_online_command(args)
		elif len(args) >= 1 and args[0] == '!!stats':
			self._on_stats_command(args)

	@staticmethod
	def _get_sender_name(data: dict) -> str:
		member = data.get('group_member') or {}
		sender = member.get('card') or member.get('nickname')
		if not sender:
			sender = str(data.get('sender_id', '未知'))
		return sender

	def _on_online_command(self, args):
		self.logger.info('!!online command triggered')
		if not chatClient.is_online():
			self.send_text('ChatBridge 客户端离线')
			return
		command = '!!online'
		if len(args) == 1:
			self.logger.info('Broadcast command "{}"'.format(command))
			chatClient.register_collector(command, chatClient.collect_online_result)
			chatClient.online_players.clear()
			chatClient.broadcast_command(command)
			threading.Timer(0.5, chatClient.stop_collect_online).start()
		else:
			client = args[1]
			self.logger.info('Sending command "{}" to client {}'.format(command, client))
			chatClient.send_command(client, command)

	def _on_stats_command(self, args):
		self.logger.info('!!stats command triggered')
		command = ' '.join(args)
		without_flags = [arg for arg in args if arg not in ('-bot', '-all')]
		if len(without_flags) != 4:
			self.send_text(StatsHelpMessage)
			return
		if not chatClient.is_online():
			self.send_text('ChatBridge 客户端离线')
			return
		client = self.config.client_to_query_stats
		self.logger.info('Sending command "{}" to client {}'.format(command, client))
		chatClient.send_command(client, command)

	def check_connection(self):
		login = self._call_api('get_login_info', {})
		if not (isinstance(login, dict) and login.get('status') == 'ok'):
			self.logger.warning('Milky protocol end is not ready: {}'.format(login))
			return
		info = login.get('data') or {}
		self.logger.info('Milky protocol end logged in as {} ({})'.format(info.get('nickname', '?'), info.get('uin', '?')))

		target_group = self._as_int(self.config.react_group_id)
		result = self._call_api('get_group_list', {})
		if not (isinstance(result, dict) and result.get('status') == 'ok'):
			return
		groups = (result.get('data') or {}).get('groups') or []
		if not isinstance(groups, list):
			return
		for group in groups:
			if self._as_int(group.get('group_id')) == target_group:
				self.logger.info('Target group: {} ({})'.format(target_group, group.get('group_name', '?')))
				return
		available = ', '.join('{}({})'.format(group.get('group_id'), group.get('group_name', '?')) for group in groups[:20])
		self.logger.warning('Target group {} is not in the group list. Available groups: {}'.format(
			target_group, available or 'none'
		))

	def send_text(self, text: str):
		self.send_segments([make_text_segment(text)])

	def send_segments(self, segments):
		with self._send_lock:
			for message in split_segments(segments, self.config.max_message_length):
				if message:
					self._call_api('send_group_message', {
						'group_id': self.config.react_group_id,
						'message': message,
					})

	def _call_api(self, api: str, params: dict) -> Optional[dict]:
		url = 'http://{}:{}/api/{}'.format(self.config.milky_address, self.config.milky_port, api)
		headers = {'Content-Type': 'application/json'}
		if self.config.milky_access_token:
			headers['Authorization'] = 'Bearer {}'.format(self.config.milky_access_token)
		try:
			response = requests.post(url, json=params, headers=headers, timeout=10)
		except requests.RequestException:
			self.logger.exception('Failed to call Milky API {}'.format(api))
			return None
		try:
			result = response.json()
		except ValueError:
			self.logger.error('Milky API {} returned a non-JSON response: HTTP {} {}'.format(
				api, response.status_code, response.text
			))
			return None
		if not isinstance(result, dict):
			self.logger.error('Milky API {} returned an unexpected JSON value: {}'.format(api, result))
			return None
		if response.status_code != 200:
			self.logger.error('Milky API {} failed with HTTP {}: {}'.format(api, response.status_code, result))
		elif result.get('status') != 'ok':
			self.logger.error('Milky API {} failed: {}'.format(api, result))
		return result


class MilkyChatBridgeClient(ChatBridgeClient):
	command_collectors = {}  # command -> List[Callable]
	online_players = {}

	def register_collector(self, command: str, callback: Callable):
		self.command_collectors.setdefault(command, []).append(callback)

	def unregister_collector(self, command: str, callback: Callable):
		if command in self.command_collectors:
			self.command_collectors[command].remove(callback)
			if not self.command_collectors[command]:
				del self.command_collectors[command]

	def on_chat(self, sender: str, payload: ChatPayload):
		global milky_bot
		if milky_bot is None:
			return
		try:
			self.logger.info('Sending chat {} to qq'.format(payload.formatted_str()))
			milky_bot.send_text('[{}] {}'.format(sender, payload.formatted_str()))
		except:
			self.logger.exception('Error in on_chat()')

	def on_command(self, sender: str, payload: CommandPayload):
		global milky_bot
		if milky_bot is None:
			return
		if payload.responded and payload.command in self.command_collectors:
			for callback in self.command_collectors[payload.command]:
				callback(sender, payload)
			return

		if not payload.responded:
			return
		if payload.command.startswith('!!stats '):
			result = StatsQueryResult.deserialize(payload.result)
			if result.success:
				messages = ['====== {} ======'.format(result.stats_name)]
				messages.extend(result.data)
				messages.append('总数：{}'.format(result.total))
				milky_bot.send_text('\n'.join(messages))
			elif result.error_code == 1:
				milky_bot.send_text('统计信息未找到')
			elif result.error_code == 2:
				milky_bot.send_text('StatsHelper 插件未加载')
		elif payload.command == '!!online':
			result = OnlineQueryResult.deserialize(payload.result)
			if result.success:
				if result.data == []:
					milky_bot.send_text('当前 {} 没有玩家在线！'.format(sender))
				else:
					milky_bot.send_text('====== {} 玩家列表 ======\n{}'.format(sender, '\n'.join(result.data)))
			elif result.error_code == 2:
				milky_bot.send_text('OnlinePlayerAPI 插件未加载')

	def collect_online_result(self, sender, payload: CommandPayload):
		result = OnlineQueryResult.deserialize(payload.result)
		self.online_players[sender] = result.data

	def stop_collect_online(self):
		global milky_bot
		chatClient.unregister_collector('!!online', self.collect_online_result)
		message = '====== 玩家列表 ======\n'
		for sender, result in self.online_players.items():
			if len(result) > 0:
				message += '【{}】(共{}人)：\n{}\n'.format(sender, len(result), '\n'.join(result))
			else:
				message += '【{}】(无在线玩家)\n'.format(sender)
		if milky_bot is not None:
			milky_bot.send_text(message)


def main():
	global chatClient, milky_bot
	config = utils.load_config(ConfigFile, MilkyConfig)
	chatClient = MilkyChatBridgeClient.create(config)
	utils.start_guardian(chatClient)
	print('Starting Milky Bot')
	milky_bot = MilkyBot(config)
	milky_bot.check_connection()
	milky_bot.start()
	print('Bye~')


if __name__ == '__main__':
	main()
