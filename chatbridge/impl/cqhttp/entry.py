import html
import json
import re
from mcdreforged.api.all import *
from typing import Optional

import requests
import matplotlib.pyplot as plt

import websocket

from chatbridge.common.logger import ChatBridgeLogger
from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl import utils
from chatbridge.impl.cqhttp.config import CqHttpConfig
from chatbridge.impl.tis.protocol import StatsQueryResult, OnlineQueryResult

ConfigFile = 'ChatBridge_CQHttp.json'
cq_bot: Optional['CQBot'] = None
chatClient: Optional['CqHttpChatBridgeClient'] = None

CQHelpMessage = '''
!!help: 显示本条帮助信息
!!ping: pong!!
!!mc <消息>: 向 MC 中发送聊天信息 <消息>
!!online: 显示正版通道在线列表
!!stats <类别> <内容> [<-bot>]: 查询统计信息 <类别>.<内容> 的排名
'''.strip()
StatsHelpMessage = '''
!!stats <类别> <内容> [<-bot>]
添加 `-bot` 来列出 bot
例子:
!!stats used diamond_pickaxe
!!stats custom time_since_rest -bot
'''.strip()



@new_thread('get_server_info')
def get_server_info(self):
	url = "http://127.0.0.1:23333/api/service/remote_services_system/?apikey=114514" #记得把114514改成自己MCSM的API key， 
	headers = {"x-requested-with": "xmlhttprequest"}
	req = requests.get(url, headers=headers)
	data = req.json()
	if data["status"] == 200:
		for i, server in enumerate(data["data"]):
			cpu_data = [point["cpu"] for point in server["cpuMemChart"]]
			mem_data = [point["mem"] for point in server["cpuMemChart"]]

			plt.rc('font',family='FangSong')
			plt.figure()
			plt.plot(cpu_data, color="red", label="CPU")
			plt.plot(mem_data, color="blue", label="RAM")
			plt.ylim(0, 100)
			plt.xlim(0, 200)
			plt.title(f"服务器{i+1}的CPU和RAM占用率")
			plt.xlabel("时间")
			plt.legend()
			plt.grid()
			plt.savefig(f'C:\server\qq_bot\data\images\server_{i+1}.png', dpi=300)
			self.send_text(f"服务器{i+1}的信息如下：\n实例(正常/总数)：{server['instance']['running']}/{server['instance']['total']}\n内存使用情况：{(server['system']['totalmem']-server['system']['freemem'])/1024**3:.2f}GB/{server['system']['totalmem']/1024**3:.2f}GB\n内存占用率：{server['system']['memUsage']*100:.2f}%\nCPU占用率：{server['system']['cpuUsage']*100:.2f}%\n[CQ:image,file=server_{i+1}.png]")

	else:
		return(f"请求失败，状态码为{data['status']}")

class CQBot(websocket.WebSocketApp):
	def __init__(self, config: CqHttpConfig):
		self.config = config
		websocket.enableTrace(True)
		url = 'ws://{}:{}/'.format(self.config.ws_address, self.config.ws_port)
		if self.config.access_token is not None:
			url += '?access_token={}'.format(self.config.access_token)
		self.logger = ChatBridgeLogger('Bot', file_handler=chatClient.logger.file_handler)
		self.logger.info('Connecting to {}'.format(url))
		# noinspection PyTypeChecker
		super().__init__(url, on_message=self.on_message, on_close=self.on_close)

	def start(self):
		self.run_forever()

	def on_message(self, _, message: str):
		try:
			if chatClient is None:
				return
			data = json.loads(message)
			if data.get('post_type') == 'message' and data.get('message_type') == 'group':
				if data['anonymous'] is None and data['group_id'] == self.config.react_group_id:
					self.logger.info('QQ chat message: {}'.format(data))
					args = data['raw_message'].split(' ')

					if len(args) == 1 and args[0] == '!!help':
						self.logger.info('!!help command triggered')
						self.send_text(CQHelpMessage)

					if len(args) == 1 and args[0] == '!!ping':
						self.logger.info('!!ping command triggered')
						self.send_text('pong!!')

					if len(args) >= 1:
						sender = data['sender']['card']
						if len(sender) == 0:
							sender = data['sender']['nickname']
						message = data['raw_message']
						message = re.sub(r'\[CQ:image,file=.*?]','[图片]', message)
						message = re.sub(r'\[CQ:share,file=.*?]','[链接]', message)
						message = re.sub(r'\[CQ:face,id=.*?]','[表情]', message)
						message = re.sub(r'\[CQ:record,file=.*?]','[语音]', message)
						message = re.sub(r"\[CQ:reply,id=.*?\]", "[回复]", message)
						pattern = r"\[CQ:at,qq=(\d+)\]"
						if re.search(pattern, message): #用于将[CQ:at,qq=某人的qq号]转发为[@某人的群昵称]
							id_list = re.findall(pattern, message)
							for id in id_list:
								#下方url请更改为你自己cqhttp bot的http请求地址，格式为 http://<ip(通常为127.0.0.1)>:<端口>/get_group_member_info?group_id=<群号>&user_id={id}&no_cache=true&access_token=<你的access_token(没有可不填)>
								card = requests.get(f"http://127.0.0.1:5700/get_group_member_info?group_id=114514&user_id={id}&no_cache=true&access_token=114514").json()['data']['card']
								message = re.sub(pattern, f"[@{card}]", message, count=1)
						text = html.unescape(message)
						chatClient.send_chat(text, sender)

					if len(args) == 1 and args[0] == '!!info':  #基于MCSM获取服务器运行信息，不用MCSM就把这几行删了，用的话请修改第42行的url
						self.logger.info('!!info command triggered')
						self.send_text('正在通过 api.tqmcraft.net 获取服务器运行信息，请稍后...') #其实api.tqmcraft.net根本没有解析到任何ip，这行只是为了好看，当然你也可以把它删了
						get_server_info(self)

					if len(args) == 1 and args[0] == '!!online':
						self.logger.info('!!online command triggered')
						if chatClient.is_online():
							command = args[0]
							client = self.config.client_to_query_online
							self.logger.info('Sending command "{}" to client {}'.format(command, client))
							chatClient.send_command(client, command)
						else:
							self.send_text('ChatBridge 客户端离线')

					if len(args) >= 1 and args[0] == '!!stats':
						self.logger.info('!!stats command triggered')
						command = '!!stats rank ' + ' '.join(args[1:])
						if len(args) == 0 or len(args) - int(command.find('-bot') != -1) != 3:
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
				"message": text
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

	def send_message(self, sender: str, message: str):
		self.send_text('[{}] {}'.format(sender, message))


class CqHttpChatBridgeClient(ChatBridgeClient):
	def on_chat(self, sender: str, payload: ChatPayload):
		global cq_bot
		if cq_bot is None:
			return
		try:
			self.logger.info('Sending message {} to qq'.format(payload.formatted_str()))
			cq_bot.send_message(sender, payload.formatted_str())
		except:
			self.logger.exception('Error in on_message()')


	def on_command(self, sender: str, payload: CommandPayload):
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
			cq_bot.send_text('====== 玩家列表 ======\n{}'.format('\n'.join(result.data)))


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
