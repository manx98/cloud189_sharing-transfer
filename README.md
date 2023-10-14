# 天翼云盘保存分享文件

## 安装依赖环境
程序运行需要使用python3环境
1. 安装pip依赖包
```shell
pip install -r requirements.txt
```

## 使用示例
运行时间受文件数量限制,保存结束程序会自动退出,请耐心等待。
```shell
python3 main.py -u "你的用户名" -p "你的密码" -d "保存到的路径" -l "分享链接"
```

## 使用帮助
使用下面命令查看详细使用帮助
```shell
python3 main.py -h
```