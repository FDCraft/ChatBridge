from typing import Optional

from mcdreforged.api.all import *

from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl.mcdr.config import MCDRClientConfig
from chatbridge.impl.tis.protocol import StatsQueryResult, OnlineQueryResult


class ChatBridgeMCDRClient(ChatBridgeClient):
	KEEP_ALIVE_THREAD_NAME = 'ChatBridge-KeepAlive'

	def __init__(self, config: MCDRClientConfig, server: ServerInterface):
		super().__init__(config.aes_key, config.client_info, server_address=config.server_address)
		self.config = config
		self.server: ServerInterface = server
		prev_handler = self.logger.console_handler
		new_handler = SyncStdoutStreamHandler()  # use MCDR's, so the concurrent output won't be messed up
		new_handler.setFormatter(prev_handler.formatter)
		self.logger.removeHandler(prev_handler)
		self.logger.addHandler(new_handler)

	def get_logging_name(self) -> str:
		return 'ChatBridge@{}'.format(hex((id(self) >> 16) & (id(self) & 0xFFFF))[2:].rjust(4, '0'))

	def _get_main_loop_thread_name(self):
		return 'ChatBridge-' + super()._get_main_loop_thread_name()

	def _get_keep_alive_thread_name(self):
		return 'ChatBridge-' + super()._get_keep_alive_thread_name()

	def _on_stopped(self):
		super()._on_stopped()
		self.logger.info('Client stopped')

	def on_chat(self, sender: str, payload: ChatPayload):
		self.server.say(RText('[{}] {}'.format(sender, payload.formatted_str()), RColor.gray))

	def on_command(self, sender: str, payload: CommandPayload):
		command = payload.command
		result: Optional[Serializable] = None
		if command.startswith('!!stats '):
			try:
				import stats_helper
			except (ImportError, ModuleNotFoundError):
				result = StatsQueryResult.no_plugin()
			else:
				trimmed_command = command.replace('-bot', '').replace('-all', '')
				res_raw: Optional[str]
				try:
					prefix, typ, cls, target = trimmed_command.split()
					assert typ == 'rank' and type(target) is str
				except:
					res_raw = None
				else:
					res_raw = stats_helper.show_rank(
						self.server.get_plugin_command_source(),
						cls, target,
						list_bot='-bot' in command,
						is_tell=False,
						is_all='-all' in command,
						is_called=True
					)
				if res_raw is not None:
					lines = res_raw.splitlines()
					stats_name = lines[0]
					total = int(lines[-1].split(' ')[1])
					result = StatsQueryResult.create(stats_name, lines[1:-1], total)
				else:
					result = StatsQueryResult.unknown_stat()
		
		if command == '!!online':
			try:
				import online_player_api
			except (ImportError, ModuleNotFoundError):
				result = OnlineQueryResult.no_plugin()
			else:
				result = OnlineQueryResult.create(online_player_api.get_player_list())

		if result is not None:
			self.reply_command(sender, payload, result)
