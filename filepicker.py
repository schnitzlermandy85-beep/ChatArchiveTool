import json,sys,tkinter as tk
from tkinter import filedialog
root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
try:
 if sys.argv[1]=='folder':result=filedialog.askdirectory(parent=root,title='选择文件夹')
 else:
  types=[('媒体压缩包','*.zip')] if sys.argv[2]=='zip' else [('聊天数据','*.json *.jsonl *.zip'),('所有文件','*.*')]
  result=filedialog.askopenfilename(parent=root,title='选择聊天导出文件',filetypes=types)
 print(json.dumps(result,ensure_ascii=False))
finally:root.destroy()
