file_path = "D:/teavar-master/code/data/B4/demand.txt"

print("--- 正在透视 demand.txt 的前 5 行 ---")
with open(file_path, "r") as f:
    for i in range(5):
        # repr() 函数会把所有隐藏的空格、Tab(\t) 和换行符(\n) 原形毕露
        print(repr(f.readline()))


        