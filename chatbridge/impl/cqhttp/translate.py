import re

# CQCode <-> Array Message
# https://docs.go-cqhttp.org/reference/#%E6%B6%88%E6%81%AF

def from_cqcode_into_array(cq_message: str) -> list :

    def parse_cq_code(cq_code):
        cq_type, cq_data = cq_code.split(',', 1)
        cq_type = cq_type[3:]
        cq_params = cq_data.split(',')
        cq_dict = {}
 
        for param in cq_params:
            key, value = param.split('=', 1)
            cq_dict[key] = value

        return {'type': cq_type, 'data': cq_dict}

    array_message = []
 
    stack = [] 
    for char in cq_message:
        if char == '[':
            if stack:
                array_message.append({'type': 'text', 'data': {'text': stack.pop()}})
            stack.append(char)
            stack.append('')
        elif char == ']':
            cq_code = ''
            while stack[-1] != '[':
                cq_code = stack.pop() + cq_code
            stack.pop()
            array_message.append(parse_cq_code(cq_code))
        else:
            if not stack:
                stack.append('')
            stack[-1] = stack[-1] + char
    
    if stack:
        array_message.append({'type': 'text', 'data': {'text': stack.pop()}})

    return array_message

def from_array_to_cqcode(array_message: list) -> str:
    args = []
    cq_message = ''
    for element in array_message:
        if element['type'] == 'text':
            args.append(element['data']['text'])
        else:
            CQCode = []
            for param, argue in element['data'].items():
                CQCode.append(f'{param}={argue}')
            args.append(fr"[CQ:{element['type']},{','.join(CQCode)}]")
    cq_message = ''.join(args)
     
    return cq_message


from_cqcode_to_cicode = lambda cq_message : re.sub(r'\[CQ:image,file=(.*?)(,.*?)*]',r'[[CICode, url=\1, name=图片]]', cq_message)

from_cicode_to_cqcode = lambda ci_message : re.sub(r'\[\[CICode,url=(.*?)(,.*?)*\]\]', r'[CQ:image,file=\1]', ci_message)