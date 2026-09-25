from tool import get_file_object,get_anthropic,get_openai,parse_sucai

tar = input("输入素材名")
a = get_anthropic(zhuti=tar)
sucai = get_openai(former_answer=a,zhuti=tar)
f=get_file_object(f"素材/{tar}.txt")
# noinspection bad-argument-type
f.write(parse_sucai(sucai))
f.close()

