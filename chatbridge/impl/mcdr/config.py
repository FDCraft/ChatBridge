from chatbridge.core.config import ClientConfig


class MCDRClientConfig(ClientConfig):
	enable: bool = True
	boardcast_player: bool = False
	debug: bool = False
