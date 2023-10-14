# 天翼云盘保存分享文件（无单次转存上限）

## 使用步骤
1. 安装依赖环境(首次运行，根据设备选择其一执行)
   + 安卓手机使用Termux  
       ```shell
       pkg update
       pkg install python3 -y
       pkg install git -y
       ```
   + Ubuntu/Debian系统
      ```shell
       sudo apt update
       sudo apt install python3 -y
       sudo apt install git -y
      ```
2. 克隆源码
    ```shell
    git clone https://github.com/manx98/cloud189_sharing-transfer.git
    ```
3. 进入源码目录
    ```shell
    cd cloud189_sharing-transfer
    ```
4. 安装依赖(首次运行需要执行)
   ```shell
    pip install -r requirements.txt
    ```
5. 执行转储分享 
   
   运行时间受文件数量限制,保存结束程序会自动退出,并打印执行结果,请耐心等待。
    ```shell
    python3 main.py -u "你的用户名" -p "你的密码" -d "保存到的路径(如 /A/B/C)" -l "分享链接(如 https://cloud.189.cn/web/share?code=XXXXXXXXX)"
    ```

## 使用帮助
使用下面命令查看详细使用帮助
```shell
python3 main.py -h
```