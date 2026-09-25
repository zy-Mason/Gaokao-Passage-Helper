from tool import get_file_object,get_anthropic,get_openai,parse_sucai

alltar = input("输入一组素材名，用空格分割：")
tars = alltar.split(" ")

print("即将整理这些素材，确认请输入y回车")
print(tars)
checkkkkk = input()
if checkkkkk == "y":
    for tar in tars:
        a = get_anthropic(zhuti=tar)
        sucai = get_openai(former_answer=a, zhuti=tar)
        f = get_file_object(f"素材/{tar}.txt")
        # noinspection bad-argument-type
        f.write(parse_sucai(sucai))
        f.close()

