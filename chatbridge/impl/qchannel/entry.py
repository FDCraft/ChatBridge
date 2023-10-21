import qqbot, re

from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.config import ClientConfig
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl.qchannel.config import QQChannelConfig
from chatbridge.impl import utils

ConfigFile = 'ChatBridge_QChannel.json'
LogFile = 'ChatBridge_QChannel.log'
RetryTime = 3
RemoveReg = re.compile(r'<@!\d+> ')


class QChannelBot():
	"""Object representing a bot instance"""
	def __init__(self, config) -> None:
		self.config = config
		self.token = qqbot.Token(config.appid, config.token)
		self.msg_api = qqbot.MessageAPI(self.token)

		def _on_message(event, message: qqbot.Message):
			"""On chat msg from QQ Channel"""
			content = '<{}>'.format(message.author.username) + RemoveReg.sub('', message.content, 1)
			qqbot.logger.info('Message sent to Minecraft server: ' + content)
			chatClient.send_chat(str(message.content))
		self.msg_handler = qqbot.Handler(qqbot.HandlerType.AT_MESSAGE_EVENT_HANDLER, _on_message)


	def start_running(self):
		qqbot.listen_events(self.token, False, self.msg_handler)

	def send_msg(self, request: qqbot.MessageSendRequest):
		self.msg_api.post_message(self.config.channel_id, request)


class QChannelBotClient(ChatBridgeClient):
	def on_chat(self, sender: str, payload: ChatPayload):
		"""On chat msg from Minecraft server"""
		req = qqbot.MessageSendRequest('[{}] <{}> {}'.format(sender, payload.author, payload.message))
		qqbot.logger.info('Message sent to QQ Channel: ' + payload.message)
		qChBot.send_msg(req)



def main():
	global chatClient, qChBot, config
	config = utils.load_config(ConfigFile, QQChannelConfig)
	chatClient = QChannelBotClient.create(config)
	utils.start_guardian(chatClient)
	print('Starting up QQ Channel Bot')
	qChBot = QChannelBot(config)
	qChBot.start_running()
	print('Closing connection.')