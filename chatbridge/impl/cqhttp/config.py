from chatbridge.core.config import ClientConfig


class CqHttpConfig(ClientConfig):
	ws_address: str = '127.0.0.1'
	ws_port: int = 5701
	ws_access_token: str = ''
	http_address: str = '127.0.0.1'
	http_port: int = 5700
	http_access_token: str = ''
	array: bool = False
	react_group_id: int = 12345
	client_to_query_stats: str = 'MyClient1'
	client_to_query_online: str = 'MyClient2'
	image_view: bool = False
