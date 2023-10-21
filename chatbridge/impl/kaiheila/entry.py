import asyncio
import collections
import json
import logging
import queue
from typing import Optional, List

from khl import Bot, Message
from khl._types import MessageTypes
from khl.card import CardMessage, Card, Module, Element, Types, Struct

from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.config import ClientConfig
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl import utils
from chatbridge.impl.kaiheila.helps import StatsCommandHelpMessage, CommandHelpMessage
from chatbridge.impl.tis import bot_util
from chatbridge.impl.tis.protocol import OnlineQueryResult, StatsQueryResult

ConfigFile = 'ChatBridge_kaiheila.json'
LogFile = 'ChatBridge_kaiheila.log'
RetryTime = 3 # second
EmbedIcon = 'https://cdn.discordapp.com/emojis/566212479487836160.png'


class KaiHeiLaConfig(ClientConfig):
	token: str = ''
	channels_for_command: List[str] = [
		'123321',
		'1234567'
	]
	channel_for_chat: str = '12344444'
	command_prefix: str = '!!'
	client_to_query_stats: str = 'MyClient1'
	client_to_query_online: str = 'MyClient2'
	server_display_name: str = 'TIS'


class MessageDataType:
	CHAT = 0
	CARD = 1
	TEXT = 2


MessageData = collections.namedtuple('MessageData', 'channel data type')

logging.basicConfig(level='INFO')
config: KaiHeiLaConfig
khlBot: Optional['KaiHeiLaBot'] = None
chatClient: Optional['KhlChatBridgeClient'] = None


class KaiHeiLaBot(Bot):
	def __init__(self, config: KaiHeiLaConfig):
		self.config = config
		super().__init__(token=self.config.token)
		self.messages = queue.Queue()
		self.event_loop = asyncio.get_event_loop()
#		self._setup_event_loop(self.event_loop)

	def startRunning(self):
		chatClient.logger.info('Starting the bot')
		asyncio.ensure_future(self.on_ready(), loop=self.event_loop)
		self.run()

	async def listeningMessage(self):
		chatClient.logger.info('Message listening looping...')
		try:
			while True:
				try:
					message_data: MessageData = self.messages.get(block=False)
				except queue.Empty:
					await asyncio.sleep(0.05)
					continue
				data = message_data.data
				if message_data.type == MessageDataType.CHAT:  # chat message
					assert isinstance(data, tuple)
					sender: str = data[0]
					payload: ChatPayload = data[1]
					await self.send(await self.client.fetch_public_channel(self.config.channel_for_chat), self.formatMessageToKaiHeiLa('[{}] {}'.format(sender, payload.formatted_str())))
				elif message_data.type == MessageDataType.CARD:  # embed
					assert isinstance(data, Card)
					await self.send(await self.client.fetch_public_channel(message_data.channel), CardMessage(data), type=MessageTypes.CARD)
				elif message_data.type == MessageDataType.TEXT:
					await self.send(await self.client.fetch_public_channel(message_data.channel), self.formatMessageToKaiHeiLa(str(data)))
				else:
					chatClient.logger.debug('Unknown messageData type {}'.format(message_data.data))
		except:
			chatClient.logger.exception('Error looping khl bot')

	async def on_ready(self):
		me = await self.client.fetch_me()
		chatClient.logger.info(f'Logged in with id {me.id}')
		await self.listeningMessage()

	def add_message(self, data, channel_id, t):
		self.messages.put(MessageData(data=data, channel=channel_id, type=t))

	def add_embed(self, title: str, text: str, channel_id: str):
		self.messages.put(MessageData(
			data=Card(
				Module.Header(title),
				Module.Section(text),
			theme='secondary', size='lg'),
			channel=channel_id, type=MessageDataType.CARD)
		)

	def add_stats_result(self, name: str, data: List[str], total: int, channel_id: str):
		rank = [line.split(' ')[0] for line in data]
		player = [line.split(' ')[1] for line in data]
		value = [bot_util.process_number(line.split(' ')[2]) for line in data]
		self.messages.put(MessageData(
			data=Card(
				Module.Header('统计信息 {}'.format(name)),
				Module.Section(
					Struct.Paragraph(
						3,
						Element.Text("**排名**\n{}".format('\n'.join(rank))),
						Element.Text("**玩家**\n{}".format('\n'.join(player))),
						Element.Text("**值**\n{}".format('\n'.join(value)))
					)
				),
				Module.Section('总数：{} | {}'.format(total, bot_util.process_number(total))),
				theme='secondary', size='lg'),
			channel=channel_id, type=MessageDataType.CARD)
		)

	def formatMessageToKaiHeiLa(self, message: str) -> str:
		# TODO when khl supports markdown
		return message


def createKaiHeiLaBot() -> KaiHeiLaBot:
	bot = KaiHeiLaBot(config)

	@bot.on_message()
	async def chat(msg: Message):
		channel_id = msg.ctx.channel.id
		author = msg.author.username
		chatClient.logger.debug('channel id = {}'.format(channel_id))
		if channel_id in config.channels_for_command or channel_id == config.channel_for_chat:
			chatClient.logger.info(f"{channel_id}: {author}: {msg.content}")
			if channel_id == config.channel_for_chat:
				if not msg.content.startswith(config.command_prefix):
					chatClient.broadcast_chat(msg.content, author=author)

	@bot.command(name='hello')
	async def world(msg: Message):
		await msg.reply('world!')

	@bot.command(name='help', prefixes=[config.command_prefix])
	async def help(msg: Message):
		if msg.ctx.channel.id in bot.config.channels_for_command:
			await msg.reply(CommandHelpMessage)

	@bot.command(name='ping', prefixes=[config.command_prefix])
	async def ping(msg: Message):
		print('pong!!')
		if msg.ctx.channel.id in bot.config.channels_for_command:
			await bot.send(msg.ctx.channel, 'pong!!')

	async def send_chatbridge_command(target_client: str, command: str, msg: Message):
		if chatClient.is_online():
			chatClient.logger.info('Sending command "{}" to client {}'.format(command, target_client))
			chatClient.send_command(target_client, command, params={'from_channel': msg.ctx.channel.id})
		else:
			await msg.reply('ChatBridge client is offline')

	@bot.command(name='online', prefixes=[config.command_prefix])
	async def online(msg: Message):
		if msg.ctx.channel.id in bot.config.channels_for_command:
			await send_chatbridge_command(config.client_to_query_online, '!!online', msg)

	@bot.command(name='stats', prefixes=[config.command_prefix])
	async def stats(msg: Message, *args):
		args = list(args)
		if len(args) >= 1 and args[0] == 'rank':
			args.pop(0)
		command = '!!stats rank ' + ' '.join(args)
		if len(args) == 0 or len(args) - int(command.find('-bot') != -1) - int(command.find('-all') != -1) != 2:
			await msg.reply(StatsCommandHelpMessage)
		else:
			await send_chatbridge_command(config.client_to_query_stats, command, msg)

	return bot


class KhlChatBridgeClient(ChatBridgeClient):
	def on_chat(self, sender: str, payload: ChatPayload):
		khlBot.add_message((sender, payload), None, MessageDataType.CHAT)

	def on_command(self, sender: str, payload: CommandPayload):
		try:
			channel_id = payload.params['from_channel']
		except KeyError:
			self.logger.warning('No channel id in command response data: {}'.format(payload.params))
			return
		if payload.command.startswith('!!stats '):
			result: StatsQueryResult = StatsQueryResult.deserialize(payload.result)
			if result.success:
				khlBot.add_stats_result(result.stats_name, result.data, result.total, channel_id)
			else:
				if result.error_code == 1:
					message = '未知或空统计信息'
				elif result.error_code == 2:
					message = '未找到StatsHelper插件'
				else:
					message = '错误代码：{}'.format(result.error_code)
				khlBot.add_message(message, channel_id, MessageDataType.TEXT)
		elif payload.command == '!!online':
			result: OnlineQueryResult = OnlineQueryResult.deserialize(payload.result)
			khlBot.add_embed('{} online players'.format(config.server_display_name), '\n'.join(result.data), channel_id)


def main():
	global chatClient, khlBot, config
	config = utils.load_config(ConfigFile, KaiHeiLaConfig)
	chatClient = KhlChatBridgeClient.create(config)
	utils.start_guardian(chatClient)
	print('Starting KHL Bot')
	khlBot = createKaiHeiLaBot()
	khlBot.startRunning()
	print('Bye~')


if __name__ == '__main__':
	main()

