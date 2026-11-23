from chatbridge.core.config import ClientConfig


class MilkyConfig(ClientConfig):
	milky_address: str = '127.0.0.1'
	milky_port: int = 3010
	milky_access_token: str = ''
	react_group_id: int = 12345
	client_to_query_stats: str = 'MyClient1'
	client_to_query_online: str = 'MyClient2'
	image_view: bool = False
	max_message_length: int = 500
