import base64
import html
import json
import os
import re
import threading
import time
from mcdreforged.api.all import *
from typing import Callable, Optional

import requests
import matplotlib.pyplot as plt

import websocket

from chatbridge.common.logger import ChatBridgeLogger
from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl import utils
from chatbridge.impl.cqhttp.config import CqHttpConfig
from chatbridge.impl.cqhttp.translate import *
from chatbridge.impl.tis.protocol import StatsQueryResult, OnlineQueryResult



ConfigFile = 'ChatBridge_CQHttp.json'
cq_bot: Optional['CQBot'] = None
chatClient: Optional['CqHttpChatBridgeClient'] = None

CQHelpMessage = '''
!!help: 显示本条帮助信息
!!ping: pong!!
!!mc <消息>: 向 MC 中发送聊天信息 <消息>
!!online: 显示正版通道在线列表
!!info: 显示服务器运行情况
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



class CQBot(websocket._app.WebSocketApp):
	def __init__(self, config: CqHttpConfig):
		self.config = config
		websocket.enableTrace(True)
		url = 'ws://{}:{}/'.format(self.config.ws_address, self.config.ws_port)
		if self.config.ws_access_token is not None and self.config.ws_access_token != '':
			url += '?access_token={}'.format(self.config.ws_access_token)
		self.logger = ChatBridgeLogger('Bot', file_handler=chatClient.logger.file_handler)
		self.logger.info('Connecting to {}'.format(url))
		# noinspection PyTypeChecker
		super().__init__(url, on_message=self.on_message, on_close=self.on_close)

	def start(self):
		self.run_forever(ping_interval=60,ping_timeout=5)

	def on_message(self, _, message: str):
		try:
			if chatClient is None:
				return
			data = json.loads(message)
			if data.get('post_type') == 'message' and data.get('message_type') == 'group':
				if data['group_id'] == self.config.react_group_id and data['user_id'] != data['self_id']:
					self.logger.info('QQ chat message: {}'.format(data))
					if self.config.array:
						raw_message = from_array_to_cqcode(data['message'])
					else:
						raw_message = data['raw_message']

					args = raw_message.split(' ')
					
					if len(args) == 1 and args[0] == '!!help':
						self.logger.info('!!help command triggered')
						self.send_text(CQHelpMessage)

					if len(args) == 1 and args[0] == '!!ping':
						self.logger.info('!!ping command triggered')
						self.send_text('pong!!')

					if len(args) >= 1:
						sender = data['sender']['card'] if data['sender']['card'] is not None and data['sender']['card'] != '' else data['sender']['nickname']

						msg = raw_message
						if "CQ:json" in msg:
							msg = "[JSON]"
						msg = re.sub(r'\[CQ:share,file=.*?\]','[链接]', msg)
						msg = re.sub(r'\[CQ:face,id=.*?\]','[表情]', msg)
						msg = re.sub(r'\[CQ:record,file=.*?\]','[语音]', msg)
						msg = re.sub(r"\[CQ:reply,id=.*?\]", "[回复]", msg)
						msg = re.sub(r"\[CQ:video(,.*)*\]", "[视频]", msg)
						#msg = re.sub(r"\[CQ:json.*?\]", "[JSON]", msg,flags=re.DOTALL)
						msg = re.sub(r'\[CQ:at,qq=all\]','[@全体]', msg)
						msg = re.sub(r'\[CQ:at,qq=.*?,name=(.*?)\]',r'[@\1]', msg)
						msg = re.sub(r'\[CQ:at,qq=(.*?)\]',r'[@\1]', msg)
						

						if self.config.image_view:
							msg = re.sub(r'\[CQ:image,.*?url=([^,\]]+)[^\]]*?\]', r'[[CICode,url=\1,name=图片]]', msg)
						else:
							msg = re.sub(r'\[CQ:image,.*?url=([^,^\]]+)[^\]]*?\]','[图片]', msg)
						text = html.unescape(msg)
						chatClient.broadcast_chat(text, author=sender)

					if len(args) == 1 and args[0] == '!!info':
						self.logger.info('!!info command triggered')
						self.send_text('正在通过api获取服务器运行信息，请稍后...')
						get_server_info(self)

					if len(args) >= 1 and args[0] in ['!!online', 'online', 'on']:
						self.logger.info('!!online command triggered')
						if chatClient.is_online():
							command = '!!online'
							if len(args) == 1:
								self.logger.info('Broadcas command "{}"'.format(command))
								chatClient.register_collector('!!online', chatClient.collect_online_result)
								chatClient.online_players = {}
								chatClient.broadcast_command(command)
								timer = threading.Timer(0.5, chatClient.stop_collect_online)
								timer.start()
							else:
								client = self.config.client_to_query_online if len(args) == 1 else args[1]
								self.logger.info('Sending command "{}" to client {}'.format(command, client))
								chatClient.send_command(client, command)
						else:
							self.send_text('ChatBridge 客户端离线')

					if len(args) >= 1 and args[0] == '!!stats':
						self.logger.info('!!stats command triggered')
						command = '!!stats ' + ' '.join(args[1:])
						if len(args) == 1 or len(args) - int(command.find('-bot') != -1) - int(command.find('-all') != -1) != 4:
							self.send_text(StatsHelpMessage)
							return
						if chatClient.is_online:
							client = self.config.client_to_query_stats
							self.logger.info('Sending command "{}" to client {}'.format(command, client))
							chatClient.send_command(client, command)
						else:
							self.send_text('ChatBridge 客户端离线')
		except:
			self.logger.exception('Error in on_message()')

	def on_close(self, *args):
		self.logger.info("Close connection")

	def _send_text(self, text):
		data = {
			"action": "send_group_msg",
			"params": {
				"group_id": self.config.react_group_id,
				"message":[{
					"type": "text",
					"data": {
						"text": text
					}
				}]
			}
		}
		self.send(json.dumps(data))

	def send_message(self, message):
		data = {
			"action": "send_group_msg",
			"params": {
				"group_id": self.config.react_group_id,
				"message": message
			}
		}
		self.send(json.dumps(data))		

	def send_text(self, text):
		msg = ''
		length = 0
		lines = text.rstrip().splitlines(keepends=True)
		for i in range(len(lines)):
			msg += lines[i]
			length += len(lines[i])
			if i == len(lines) - 1 or length + len(lines[i + 1]) > 500:
				self._send_text(msg)
				msg = ''
				length = 0


@new_thread('get_server_info')
def get_server_info(self: CQBot):
	url = f"http://{self.config.mcsm_address}:{self.config.mcsm_port}/api/service/remote_services_system/?apikey={self.config.mcsm_apikey}"
	headers = {"x-requested-with": "xmlhttprequest"}
	req = requests.get(url, headers=headers)
	data = req.json()
	if data["status"] == 200:
		for i, server in enumerate(data["data"]):
			cpu_data = [point["cpu"] for point in server["cpuMemChart"]]
			mem_data = [point["mem"] for point in server["cpuMemChart"]]

			plt.figure()
			plt.plot(cpu_data, color="red", label="CPU")
			plt.plot(mem_data, color="blue", label="RAM")
			plt.ylim(0, 100)
			plt.xlim(0, 200)
			plt.title("CPU & RAM")
			plt.xlabel("Time")
			plt.legend()
			plt.grid()

			if os.path.exists('./image'):
				pass
			else:
				os.mkdir('./image')			

			with open(f'./image/server_{i+1}.png', 'wb+') as image:
				plt.savefig(f'./image/server_{i+1}.png', dpi=300)
				base_string = 'base64://' + base64.b64encode(image.read()).decode('utf-8')
			message = f"服务器{i+1}的信息如下：\n实例(正常/总数)：{server['instance']['running']}/{server['instance']['total']}\n内存使用情况：{(server['system']['totalmem']-server['system']['freemem'])/1024**3:.2f}GB/{server['system']['totalmem']/1024**3:.2f}GB\n内存占用率：{server['system']['memUsage']*100:.2f}%\nCPU占用率：{server['system']['cpuUsage']*100:.2f}%\n[CQ:image,file={base_string}]"

			if self.config.array:
				message = from_cqcode_into_array(message)
				self.send_message(message)
			else:
				self.send_text(message)


	else:
		self.send_text(f"请求失败，状态码为{data['status']}")


class CqHttpChatBridgeClient(ChatBridgeClient):
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
		global cq_bot
		if cq_bot is None:
			return
		try:
			self.logger.info('Sending chat {} to qq'.format(payload.formatted_str()))
			cq_bot.send_text(f'[{sender}] {payload.formatted_str()}')
		except:
			self.logger.exception('Error in on_chat()')


	def on_command(self, sender: str, payload: CommandPayload):
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
				cq_bot.send_text('\n'.join(messages))
			elif result.error_code == 1:
				cq_bot.send_text('统计信息未找到')
			elif result.error_code == 2:
				cq_bot.send_text('StatsHelper 插件未加载')
		elif payload.command == '!!online':
			result = OnlineQueryResult.deserialize(payload.result)
			if result.success:
				if result.data == []:
					cq_bot.send_text('当前 {} 没有玩家在线！'.format(sender))
				else:
					cq_bot.send_text('====== {} 玩家列表 ======\n{}'.format(sender, '\n'.join(result.data)))
			elif result.error_code == 2:
				cq_bot.send_text('OnlinePlayerAPI 插件未加载')

	def collect_online_result(self, sender, payload: CommandPayload):
		result = OnlineQueryResult.deserialize(payload.result)
		self.online_players[sender] = result.data
  
	def stop_collect_online(self):
		chatClient.unregister_collector('!!online', self.collect_online_result)
		message = '====== 玩家列表 ======\n'
		for sender, result in self.online_players.items():
			if len(result) > 0:
				message += '【{}】(共{}人)：\n{}\n'.format(sender, len(result), '\n'.join(result))
			else:
				message += '【{}】(无在线玩家)\n'.format(sender)
		cq_bot.send_text(message)

def main():
	global chatClient, cq_bot
	config = utils.load_config(ConfigFile, CqHttpConfig)
	chatClient = CqHttpChatBridgeClient.create(config)
	utils.start_guardian(chatClient)
	print('Starting CQ Bot')
	cq_bot = CQBot(config)
	cq_bot.start()
	print('Bye~')


if __name__ == '__main__':
	main()
