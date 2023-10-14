import json
import time

import requests
from urllib import parse
from concurrent.futures import ThreadPoolExecutor
import threading
from Crypto.Cipher import PKCS1_v1_5 as Cipher_pksc1_v1_5
from Crypto.PublicKey import RSA
import logging
import argparse
from tqdm import tqdm

log = logging.getLogger()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def rsaEncrpt(password, public_key):
    rsakey = RSA.importKey(public_key)
    cipher = Cipher_pksc1_v1_5.new(rsakey)
    return cipher.encrypt(password.encode()).hex()


def format_size(size):
    units = ['B', 'KB', 'MB', 'GB', 'TB']

    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    return f"{size:.2f} {units[unit_index]}"


config = {
    "clientId": '538135150693412',
    "model": 'KB2000',
    "version": '9.0.6',
    "pubKey": 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCZLyV4gHNDUGJMZoOcYauxmNEsKrc0TlLeBEVVIIQNzG4WqjimceOj5R9ETwDeeSN3yejAKLGHgx83lyy2wBjvnbfm/nLObyWwQD/09CmpZdxoFYCH6rdDjRpwZOZ2nXSZpgkZXoOBkfNXNxnN74aXtho2dqBynTw3NFTWyQl8BQIDAQAB',
}


class BatchSaveTask:
    def __init__(self, shareInfo, batchSize, targetFolderId, shareFolderId=None, maxWorkers=3):
        self.shareInfo = shareInfo
        self.batchSize = batchSize
        self.shareFolderId = shareFolderId
        self.targetFolderId = targetFolderId
        self.tqLock = threading.Lock()
        self.taskNum = 0
        self.walkDirNum = 0
        self.saveDirNum = 0
        self.savedFileNum = 0
        self.savedFileSize = 0
        self.failed = False
        self.threadPool = ThreadPoolExecutor(max_workers=maxWorkers)
        self.tq = tqdm(desc='正在保存')

    def __updateTq(self, num=1):
        data = {
            "剩余任务数": self.taskNum,
            "已保存文件数": self.savedFileNum,
            "已保存目录数:": self.saveDirNum,
            "已遍历目录数:": self.walkDirNum,
            "已保存文件总大小": format_size(self.savedFileSize)
        }
        if num:
            self.tq.set_postfix(data, refresh=False)
            self.tq.update(num)
        else:
            self.tq.set_postfix(data)

    def __incTaskNum(self, num):
        self.tqLock.acquire()
        self.taskNum += num
        self.__updateTq(0)
        self.tqLock.release()

    def getTaskNum(self):
        self.tqLock.acquire()
        num = self.taskNum
        self.tqLock.release()
        return num

    def __incWalkDirNum(self, num=1):
        self.tqLock.acquire()
        self.walkDirNum += num
        self.__updateTq(num)
        self.tqLock.release()

    def __incSaveDirNum(self, num=1):
        self.tqLock.acquire()
        self.saveDirNum += num
        self.__updateTq(num)
        self.tqLock.release()

    def __incSavedFileInfo(self, fileInfos):
        fileNum = len(fileInfos)
        totalSize = 0
        for i in fileInfos:
            totalSize += i.get("size")
        self.tqLock.acquire()
        self.savedFileNum += fileNum
        self.savedFileSize += totalSize
        self.__updateTq(fileNum)
        self.tqLock.release()

    def run(self, checkInterval=1):
        with self.tq:
            self.__incTaskNum(1)
            self.threadPool.submit(self.__batchSave, self.targetFolderId, self.shareFolderId)
            while self.getTaskNum() > 0:
                time.sleep(checkInterval)
            self.threadPool.shutdown()
        return self.failed

    def __testAndSaveDir(self, folderInfo, targetFolderId):
        try:
            folderName = folderInfo["name"]
            shareFolderId = folderInfo["id"]
            code = self.shareInfo.saveShareFiles([{
                "fileId": shareFolderId,
                "fileName": folderName,
                "isFolder": 1}],
                targetFolderId)
            if code:
                if code == "ShareDumpFileOverload":
                    try:
                        nextFolderId = self.shareInfo.client.createFolder(parentFolderId=targetFolderId,
                                                                          name=folderName)
                        if nextFolderId:
                            self.__incTaskNum(1)
                            self.threadPool.submit(self.__batchSave, nextFolderId, shareFolderId)
                            return
                        else:
                            log.error(f"failed to create folder[{folderInfo}] at [{targetFolderId}]")
                    except Exception as e1:
                        log.error(f"failed to create folder[{folderInfo}] at [{targetFolderId}]: {e1}")
                else:
                    log.error(f"save dir response unknown code: {code}")
            else:
                self.__incSaveDirNum()
        except Exception as e2:
            log.error(f"TestAndSaveDir occurred exception: {e2}")
        finally:
            self.__incTaskNum(-1)
        self.failed = True

    def __mustSave(self, saveFiles, targetFolderId):
        try:
            taskInfos = []
            for fileInfo in saveFiles:
                taskInfos.append(
                    {
                        "fileId": fileInfo.get("id"),
                        "fileName": fileInfo.get("name"),
                        "isFolder": 0
                    }
                )
            code = self.shareInfo.saveShareFiles(taskInfos, targetFolderId)
            if code:
                log.error(f"save only files response unexpected code [num={len(saveFiles)}][code: {code}]")
            else:
                self.__incSavedFileInfo(saveFiles)
                return
        except Exception as e1:
            log.error(f"mustSave occurred exception: {e1}")
        finally:
            self.__incTaskNum(-1)
        self.failed = True

    def __splitFileListAndSave(self, fileList: list, targetFolderId):
        for i in range(0, len(fileList), self.batchSize):
            if self.failed:
                return
            self.__incTaskNum(1)
            self.threadPool.submit(self.__mustSave, fileList[i: i + self.batchSize], targetFolderId)

    def __batchSave(self, targetFolderId, shareFolderId: None):
        try:
            rootFiles = self.shareInfo.getAllShareFiles(shareFolderId)
            self.__incWalkDirNum()
            self.__splitFileListAndSave(rootFiles["files"], targetFolderId)

            for folderInfo in rootFiles["folders"]:
                if self.failed:
                    return
                self.__incTaskNum(1)
                self.threadPool.submit(self.__testAndSaveDir, folderInfo, targetFolderId)
            return
        except Exception as e1:
            log.error(f"batchSave occurred exception: {e1}")
        finally:
            self.__incTaskNum(-1)
        self.failed = True


class Cloud189ShareInfo:
    def __init__(self, shareDirFileId, shareId, shareMode, cloud189Client):
        self.shareDirFileId = shareDirFileId
        self.shareId = shareId
        self.session = cloud189Client.session
        self.client = cloud189Client
        self.shareMode = shareMode

    def getAllShareFiles(self, folder_id=None):
        if folder_id is None:
            folder_id = self.shareDirFileId
        fileList = []
        folders = []
        pageNumber = 1
        while True:
            result = self.session.get("https://cloud.189.cn/api/open/share/listShareDir.action", params={
                "pageNum": pageNumber,
                "pageSize": "10000",
                "fileId": folder_id,
                "shareDirFileId": self.shareDirFileId,
                "isFolder": "true",
                "shareId": self.shareId,
                "shareMode": self.shareMode,
                "iconOption": "5",
                "orderBy": "lastOpTime",
                "descending": "true",
                "accessCode": "",
            }).json()
            if result['res_code'] != 0:
                raise Exception(result['res_message'])
            fileListAO = result["fileListAO"]
            if fileListAO["fileListSize"] == 0:
                break
            fileList += fileListAO["fileList"]
            folders += fileListAO["folderList"]
            pageNumber += 1
        return {"files": fileList, "folders": folders}

    def saveShareFiles(self, tasksInfos, targetFolderId):
        """
        保存文件到指定路径
        :param tasksInfos: [{"fileId":"32313191387622589","fileName":"高血脂食疗药膳.epub","isFolder":0}]
        :param targetFolderId: 保存到当前账户的指定目录：12474193948415710
        :return: "ShareDumpFileOverload"、None
        """
        result = self.session.post("https://cloud.189.cn/api/open/batch/createBatchTask.action", data={
            "type": "SHARE_SAVE",
            "taskInfos": json.dumps(tasksInfos),
            "targetFolderId": targetFolderId,
            "shareId": self.shareId,
        }).json()
        if result["res_code"] != 0:
            raise Exception(result.res_message)
        taskId = result["taskId"]
        while True:
            result = self.session.post("https://cloud.189.cn/api/open/batch/checkBatchTask.action", data={
                "taskId": taskId,
                "type": "SHARE_SAVE"
            }).json()
            taskStatus = result["taskStatus"]
            errorCode = result.get("errorCode")
            if taskStatus != 3 or errorCode:
                break
            time.sleep(1)
        return errorCode

    def createBatchSaveTask(self, targetFolderId, batchSize, shareFolderId=None, maxWorkers=3):
        return BatchSaveTask(shareInfo=self, batchSize=batchSize, targetFolderId=targetFolderId,
                             shareFolderId=shareFolderId, maxWorkers=3)


class Cloud189:
    def __init__(self):
        self.session = requests.session()
        self.session.headers = {
            'User-Agent': f"Mozilla/5.0 (Linux; U; Android 11; {config['model']} Build/RP1A.201005.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36 Ecloud/{config['version']} Android/30 clientId/{config['clientId']} clientModel/{config['model']} clientChannelId/qq proVersion/1.0.6",
            "Accept": "application/json;charset=UTF-8",
        }

    def getObjectFolderNodes(self, folderId=-11):
        """
        获取目录列表
        :param folderId: 目录ID
        :return: [{"isParent": "true", "name": "ePUBee图书", "pId": "-11", "id": "12474193948415710"}]
        """
        return self.session.post("https://cloud.189.cn/api/portal/getObjectFolderNodes.action", data={
            "id": folderId,
            "orderBy": 1,
            "order": "ASC"
        }).json()

    def getFolderIdByPath(self, path, folderId=-11):
        """
        通过路径获取目录ID
        :param path: 路径
        :param folderId: 起始目录ID
        :return: 目录ID
        """
        path = path.strip("/")
        if not path:
            return folderId
        for name in path.split("/"):
            found = False
            filesData = self.getObjectFolderNodes(folderId)
            for node in filesData:
                if node["name"] == name:
                    folderId = node["id"]
                    found = True
                    break
            if not found:
                return None
        return folderId

    def getShareInfo(self, link):
        code = parse.parse_qs(parse.urlparse(link).query)["code"][0]
        result = self.session.get("https://cloud.189.cn/api/open/share/getShareInfoByCodeV2.action", params={
            "shareCode": code
        }).json()
        if result['res_code'] != 0:
            raise Exception(result['res_message'])
        return Cloud189ShareInfo(
            shareId=result["shareId"],
            shareDirFileId=result["fileId"],
            cloud189Client=self,
            shareMode=result["shareMode"]
        )

    def getEncrypt(self):
        result = self.session.post("https://open.e.189.cn/api/logbox/config/encryptConf.do", data={
            'appId': 'cloud'
        }).json()
        return result['data']['pubKey']

    def getRedirectURL(self):
        rsp = self.session.get('https://cloud.189.cn/api/portal/loginUrl.action?redirectURL=https://cloud.189.cn/web'
                               '/redirect.html?returnURL=/main.action')
        if rsp.status_code == 200:
            return parse.parse_qs(parse.urlparse(rsp.url).query)
        else:
            raise Exception(f"status code must be 200, but real is {rsp.status_code}")

    def getLoginFormData(self, username, password, encryptKey):
        query = self.getRedirectURL()
        resData = self.session.post('https://open.e.189.cn/api/logbox/oauth2/appConf.do', data={
            "version": '2.0',
            "appKey": 'cloud',
        }, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:74.0) Gecko/20100101 Firefox/76.0',
            "Referer": 'https://open.e.189.cn/',
            "lt": query["lt"][0],
            "REQID": query["reqId"][0],
        }).json()
        if resData.get('result') == '0':
            keyData = f"-----BEGIN PUBLIC KEY-----\n{encryptKey}\n-----END PUBLIC KEY-----"
            usernameEncrypt = rsaEncrpt(username, keyData)
            passwordEncrypt = rsaEncrpt(password, keyData)
            return {
                "returnUrl": resData['data']['returnUrl'],
                "paramId": resData['data']['paramId'],
                "lt": query['lt'][0],
                "REQID": query['reqId'][0],
                "userName": f"{{NRP}}{usernameEncrypt}",
                "password": f"{{NRP}}{passwordEncrypt}",
            }
        else:
            raise Exception(resData["msg"])

    def login(self, username, password):
        encryptKey = self.getEncrypt()
        formData = self.getLoginFormData(username, password, encryptKey)
        data = {
            "appKey": 'cloud',
            "version": '2.0',
            "accountType": '01',
            "mailSuffix": '@189.cn',
            "validateCode": '',
            "returnUrl": formData['returnUrl'],
            "paramId": formData['paramId'],
            "captchaToken": '',
            "dynamicCheck": 'FALSE',
            "clientType": '1',
            "cb_SaveName": '0',
            "isOauth2": "false",
            "userName": formData['userName'],
            "password": formData['password'],
        }
        result = self.session.post('https://open.e.189.cn/api/logbox/oauth2/loginSubmit.do', data=data, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:74.0) Gecko/20100101 Firefox/76.0',
            'Referer': 'https://open.e.189.cn/',
            'lt': formData['lt'],
            'REQID': formData['REQID'],
        }).json()
        if result['result'] == 0:
            self.session.get(result['toUrl'], headers={
                "Referer": 'https://m.cloud.189.cn/zhuanti/2016/sign/index.jsp?albumBackupOpened=1',
                'Accept-Encoding': 'gzip, deflate',
                "Host": 'cloud.189.cn',
            })
        else:
            raise Exception(result['msg'])

    def createFolder(self, name, parentFolderId=-11):
        """
        创建目录返回文件ID
        :param parentFolderId: 父目录ID
        :param name: 要创建的文件ID
        :return:
        """
        result = self.session.post("https://cloud.189.cn/api/open/file/createFolder.action", data={
            "parentFolderId": parentFolderId,
            "folderName": name,
        }).json()
        if result["res_code"] != 0:
            raise Exception(result["res_message"])
        return result["id"]

    def mkdirAll(self, path, parentFolderId=-11):
        """
        创建所有路径
        :param path: 需要创建的路径
        :param parentFolderId: 父目录ID
        :return: 创建完成的目录ID
        """
        path = path.strip("/")
        if path:
            for name in path.split("/"):
                parentFolderId = self.createFolder(name=name, parentFolderId=parentFolderId)
        return parentFolderId


def getArgs():
    parser = argparse.ArgumentParser(description="天翼云盘保存分享文件(无单次转存上限)")
    parser.add_argument('-l', help='分享链接(形如 https://cloud.189.cn/web/share?code=XXXXXXXXX)', required=True)
    parser.add_argument('-u', help='云盘用户名', required=True)
    parser.add_argument('-p', help='云盘用户密码', required=True)
    parser.add_argument('-d', help='保存到的云盘的路径(不存在会自动创建, 形如: /A/B)', required=True)
    parser.add_argument('-t', help='转存线程数', default=5)
    return parser.parse_args()


if __name__ == '__main__':
    args = getArgs()
    client = Cloud189()
    try:
        log.info("正在登录 ...")
        client.login(args.u, args.p)
    except Exception as e:
        log.error(f"登录出现错误: {e}")
        exit(-1)
    log.info("正在获取文件分享信息...")
    info = None
    try:
        info = client.getShareInfo(args.l)
    except Exception as e:
        log.info(f"获取分享信息出现错误: {e}")
        exit(-1)
    log.info("正在检查并创建目录...")
    saveDir = None
    try:
        saveDir = client.mkdirAll(args.d)
    except Exception as e:
        log.error(f"检查并创建目录出现错误: {e}")
        exit(-1)
    if not saveDir:
        log.error("无法获取保存目录信息")
    else:
        ret = info.createBatchSaveTask(saveDir, 500, maxWorkers=args.t).run()
        if ret:
            log.info("所有分享文件已保存.")
            exit(0)
        else:
            log.error("保存分享文件出现出现错误")
    exit(-1)
