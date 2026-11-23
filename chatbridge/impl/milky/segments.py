from typing import Dict, List


MessageSegment = Dict[str, dict]


def make_text_segment(text: str) -> MessageSegment:
	return {'type': 'text', 'data': {'text': text}}


def segments_to_text(segments: List[MessageSegment], *, image_view: bool = False) -> str:
	"""Render incoming Milky segments as plain text for the ChatBridge boundary."""
	parts = []
	for segment in segments:
		segment_type = segment.get('type')
		data = segment.get('data') or {}
		if segment_type == 'text':
			parts.append(data.get('text', ''))
		elif segment_type == 'mention':
			name = data.get('name')
			parts.append('@{}'.format(name if name else data.get('user_id', '')))
		elif segment_type == 'mention_all':
			parts.append('[@全体]')
		elif segment_type == 'face':
			parts.append('[表情]')
		elif segment_type == 'reply':
			parts.append('[回复]')
		elif segment_type == 'image':
			temp_url = data.get('temp_url')
			if image_view and temp_url:
				parts.append('[[CICode,url={},name=图片]]'.format(temp_url))
			else:
				parts.append('[图片]')
		elif segment_type == 'record':
			parts.append('[语音]')
		elif segment_type == 'video':
			parts.append('[视频]')
		elif segment_type == 'file':
			file_name = data.get('file_name')
			parts.append('[文件:{}]'.format(file_name) if file_name else '[文件]')
		elif segment_type == 'forward':
			parts.append('[合并转发]')
		elif segment_type == 'market_face':
			parts.append('[表情]')
		elif segment_type == 'light_app':
			parts.append('[小程序]')
		elif segment_type == 'xml':
			parts.append('[XML]')
		elif segment_type == 'markdown':
			parts.append('[MD]')
		else:
			parts.append('[{}]'.format(segment_type or '未知'))
	return ''.join(parts)


def split_segments(segments: List[MessageSegment], max_length: int) -> List[List[MessageSegment]]:
	"""Split a segment array into several arrays without breaking text segments."""
	if max_length <= 0:
		max_length = 1

	messages: List[List[MessageSegment]] = []
	current: List[MessageSegment] = []
	current_length = 0

	def flush():
		nonlocal current, current_length
		if current:
			messages.append(current)
			current = []
			current_length = 0

	for segment in segments:
		if segment.get('type') != 'text':
			current.append(segment)
			continue

		text: str = (segment.get('data') or {}).get('text', '')
		while text:
			remaining = max_length - current_length
			if remaining <= 0:
				flush()
				continue
			chunk, text = text[:remaining], text[remaining:]
			current.append(make_text_segment(chunk))
			current_length += len(chunk)
			if text:
				flush()

	flush()
	return messages


def segment_text(segments: List[MessageSegment]) -> str:
	"""Concatenate only the text segments, used for command matching."""
	return ''.join(
		(segment.get('data') or {}).get('text', '')
		for segment in segments
		if segment.get('type') == 'text'
	)
