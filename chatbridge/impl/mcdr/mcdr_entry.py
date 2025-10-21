import os
import shutil
from threading import Event, Lock
from typing import Optional

from mcdreforged.api.all import *

from chatbridge.core.client import ChatBridgeClient
from chatbridge.core.network.protocol import ChatPayload, CommandPayload
from chatbridge.impl import utils
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
			result = OnlineQueryResult.create(self.config.name, get_player_list())
   
		if result is not None:
			self.reply_command(sender, payload, result)


META = ServerInterface.get_instance().as_plugin_server_interface().get_self_metadata()
Prefixes = ('!!ChatBridge', '!!cb')
client: Optional[ChatBridgeMCDRClient] = None
config: Optional[MCDRClientConfig] = None
plugin_unload_flag = False
cb_stop_done = Event()
cb_lock = Lock()

online_players = []

def check_online(player: str) -> bool:
	"""Check a player is online"""
	return player in online_players

def get_player_list() -> list[str]:
    """Get all online player list"""
    return online_players.copy()

def tr(key: str, *args, **kwargs) -> RTextBase:
	return ServerInterface.get_instance().rtr(META.id + '.' + key, *args, **kwargs)


def display_help(source: CommandSource):
	source.reply(tr('help_message', version=META.version, prefix=Prefixes[0], prefixes=', '.join(Prefixes)))


def display_status(source: CommandSource):
	if config is None or client is None:
		source.reply(tr('status.not_init'))
	else:
		source.reply(tr('status.info', client.is_online(), client.get_ping_text()))


@new_thread('ChatBridge-restart')
def restart_client(source: CommandSource):
	with cb_lock:
		client.restart()
	source.reply(tr('restarted'))


@new_thread('ChatBridge-unload')
def on_unload(server: PluginServerInterface):
	global plugin_unload_flag
	plugin_unload_flag = True
	with cb_lock:
		if client is not None and client.is_running():
			server.logger.info('Stopping chatbridge client due to plugin unload')
			client.stop()
	cb_stop_done.set()


@new_thread('ChatBridge-messenger')
def send_chat(message: str, *, author: str = ''):
	with cb_lock:
		if client is not None:
			if not client.is_running():
				client.start()
			if client.is_online():
				client.broadcast_chat(message, author)


def on_load(server: PluginServerInterface, old_module):
	global online_players
	if old_module is not None and hasattr(old_module, 'online_players'):
		online_players = old_module.online_players    

	cb1_config_path = os.path.join('config', 'ChatBridge_client.json')
	config_path = os.path.join(server.get_data_folder(), 'config.json')
	if os.path.isfile(cb1_config_path) and not os.path.isfile(config_path):
		shutil.copyfile(cb1_config_path, config_path)
		server.logger.info('Migrated configure file from ChatBridge v1: {} -> {}'.format(cb1_config_path, config_path))
		server.logger.info('You need to delete the old config file manually if you want')

	global client, config
	if not os.path.isfile(config_path):
		server.logger.exception('Config file not found! ChatBridge will not work properly')
		server.logger.error('Fill the default configure file with correct values and reload the plugin')
		server.save_config_simple(MCDRClientConfig.get_default())
		return

	try:
		config = server.load_config_simple(file_name=config_path, in_data_folder=False, target_class=MCDRClientConfig)
	except:
		server.logger.exception('Failed to read the config file! ChatBridge might not work properly')
		server.logger.error('Fix the configure file and then reload the plugin')
		config.enable = False

	if not config.enable:
		server.logger.info('ChatBridge is disabled')
		return

	client = ChatBridgeMCDRClient(config, server)
	if config.debug:
		client.logger.set_debug_all(True)
	for prefix in Prefixes:
		server.register_help_message(prefix, tr('help_summary'))
	server.register_command(
		Literal(Prefixes).
		runs(display_help).
		then(Literal('status').runs(display_status)).
		then(Literal('restart').runs(restart_client))
	)

	@new_thread('ChatBridge-start')
	def start():
		with cb_lock:
			if isinstance(getattr(old_module, 'cb_stop_done', None), type(cb_stop_done)):
				stop_event: Event = old_module.cb_stop_done
				if not stop_event.wait(30):
					server.logger.warning('Previous chatbridge instance does not stop for 30s')
			server.logger.info('Starting chatbridge client')
			client.start()
			utils.start_guardian(client, wait_time=60, loop_condition=lambda: not plugin_unload_flag)

	start()


def on_user_info(server: PluginServerInterface, info: Info):
	if info.is_from_server:
		send_chat(info.content, author=info.player)


def on_player_joined(server: PluginServerInterface, player_name: str, info: Info):
	if player_name not in online_players:
		online_players.append(player_name)
	if config.boardcast_player:
		send_chat('{} joined {}'.format(player_name, config.name))


def on_player_left(server: PluginServerInterface, player_name: str):
	if player_name in online_players:
		online_players.remove(player_name)
	if config.boardcast_player:
		send_chat('{} left {}'.format(player_name, config.name))


def on_server_startup(server: PluginServerInterface):
	send_chat('Server has started up')


def on_server_stop(server: PluginServerInterface, return_code: int):
	send_chat('Server stopped')
	global online_players
	online_players = []


@event_listener('more_apis.death_message')
def on_player_death(server: PluginServerInterface, message: str):
	send_chat(message)
