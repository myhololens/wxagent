# web weixin protocol

import os, sys
import json, re
import enum
import magic
import math

from PyQt5.QtCore import *
from PyQt5.QtNetwork import *
from PyQt5.QtDBus import *


import wxagent.filestore as filestore
from .imrelayfactory import IMRelayFactory
from .wxcommon import *
from .wxsession import *
from .unimessage import *
from .wxprotocol import *
from .botcmd import *


# QDBUS_DEBUG


class ToxDispatcher(QObject):
    def __init__(self):
        "docstring"

        return

    # @param msg WXMessage
    def send(self, msg):
        return


class Chatroom():
    def __init__(self):
        "docstring"

        self.group_number = -1
        self.peer_number = -1

        # 以收到消息创建聊天群组时的from/to定义
        self.FromUser = None
        self.ToUser = None

        self.title = ''

        self.unsend_queue = []

        # temporary fix some bugs
        self.FromUserName = ''  # case for newsapp/xxx
        return


#
#
#
class WX2Tox(QObject):

    def __init__(self, parent = None):
        "docstring"
        super(WX2Tox, self).__init__(parent)

        self.wxses = None
        self.peerRelay = None

        ##### state
        self.qrpic = None  # QByteArray
        self.qrfile = ''
        self.need_send_qrfile = False   # 有可能peerRelay还未上线
        self.need_send_notify = False   # 有可能peerRelay还未上线
        self.wx2tox_msg_buffer = []  # 存储未转发到tox的消息
        self.tox2wx_msg_buffer = []

        self.wxchatmap = {}  # cname => Chatroom
        self.toxchatmap = {}  # group_number => Chatroom
        self.wxproto = WXProtocol()
        self.pendingGroupMessages = {}  # group name => msg

        #####
        self.sysbus = QDBusConnection.systemBus()
        self.sysiface = QDBusInterface(WXAGENT_SERVICE_NAME, '/io/qtc/wxagent', WXAGENT_IFACE_NAME, self.sysbus)

        #                                   path   iface    name
        # sigmsg = QDBusMessage.createSignal("/", 'signals', "logined")
        # connect(service, path, interface, name, QObject * receiver, const char * slot)
        # self.sysbus.connect(SERVICE_NAME, "/", 'signals', 'logined', self.onDBusLogined)
        self.sysbus.connect(WXAGENT_SERVICE_NAME, "/io/qtc/wxagent/signals", 'io.qtc.wxagent.signals', 'logined', self.onDBusLogined)
        self.sysbus.connect(WXAGENT_SERVICE_NAME, "/io/qtc/wxagent/signals", 'io.qtc.wxagent.signals', 'logouted', self.onDBusLogouted)
        self.sysbus.connect(WXAGENT_SERVICE_NAME, "/io/qtc/wxagent/signals", 'io.qtc.wxagent.signals', 'newmessage', self.onDBusNewMessage)

        self.sysbus.connect(WXAGENT_SERVICE_NAME, "/io/qtc/wxagent/signals", 'io.qtc.wxagent.signals', 'beginlogin', self.onDBusBeginLogin)
        self.sysbus.connect(WXAGENT_SERVICE_NAME, "/io/qtc/wxagent/signals", 'io.qtc.wxagent.signals', 'gotqrcode', self.onDBusGotQRCode)
        self.sysbus.connect(WXAGENT_SERVICE_NAME, "/io/qtc/wxagent/signals", 'io.qtc.wxagent.signals', 'loginsuccess', self.onDBusLoginSuccess)

        self.asyncWatchers = {}   # watcher => arg0

        self.initRelay()
        self.startWXBot()
        return

    def initRelay(self):
        self.peerRelay = IMRelayFactory.create('xmpp')
        # self.peerRelay = IMRelayFactory.create('tox')
        self.peerRelay.src_pname = 'WXU'

        relay = self.peerRelay
        relay.connected.connect(self.onRelayConnected, Qt.QueuedConnection)
        relay.disconnected.connect(self.onRelayDisconnected, Qt.QueuedConnection)
        relay.newMessage.connect(self.onRelayMessage, Qt.QueuedConnection)

        relay.peerConnected.connect(self.onRelayPeerConnected, Qt.QueuedConnection)
        relay.peerDisconnected.connect(self.onRelayPeerDisconnected, Qt.QueuedConnection)
        relay.newGroupMessage.connect(self.onRelayGroupMessage, Qt.QueuedConnection)
        relay.peerEnterGroup.connect(self.onRelayPeerEnterGroup, Qt.QueuedConnection)
        return

    def onRelayConnected(self):
        qDebug('hehee')

        if self.need_send_qrfile is True:
            # from .secfg import peer_xmpp_user
            url = filestore.upload_file(self.qrpic.data())
            rc = self.peerRelay.sendMessage('test qrpic url....' + url,
                                            self.peerRelay.peer_user)
            if rc is not False:
                self.need_send_qrfile = False

        if self.need_send_notify is True:
            blen = len(self.notify_buffer)
            while len(self.notify_buffer) > 0:
                notify_msg = self.notify_buffer.pop()
                self.peerRelay.sendMessage(notify_msg, self.peerRelay.peer_user)
                qDebug('send buffered notify msg: %s' % blen)
            self.need_send_notify = False

        return

    def onRelayDisconnected(self):
        qDebug('hehee')
        return

    def onRelayPeerConnected(self):
        qDebug('hehee')

        if self.need_send_qrfile is True:
            # from .secfg import peer_xmpp_user
            url = filestore.upload_file(self.qrpic.data())
            rc = self.peerRelay.sendMessage('test qrpic url....' + url,
                                            self.peerRelay.peer_user)
            if rc is not False:
                self.need_send_qrfile = False

        # TODO 使用dispatch方式发送消息
        if len(self.wx2tox_msg_buffer) > 0:
            blen = len(self.wx2tox_msg_buffer)
            while len(self.wx2tox_msg_buffer) > 0:
                msg = self.wx2tox_msg_buffer.pop()
                self.peerRelay.sendMessage(msg, self.peerRelay.peer_user)
                # ## TODO 如果发送失败，这条消息可就丢失了。
            qDebug('send buffered wx2tox msg: %s' % blen)
        return

    def onRelayPeerDisconnected(self):
        qDebug('hehee')
        return

    def onRelayPeerEnterGroup(self, group_number):
        qDebug(('hehee:' + group_number).encode())

        qDebug(str(self.toxchatmap.keys()).encode())

        groupchat = self.toxchatmap[group_number]
        qDebug('unsend queue: %s ' % len(groupchat.unsend_queue))

        unsends = groupchat.unsend_queue
        groupchat.unsend_queue = []

        idx = 0
        for fmtcc in unsends:
            # assert groupchat is not None
            rc = self.peerRelay.sendGroupMessage(fmtcc, groupchat.group_number)
            if rc is False:
                qDebug('group chat send msg error:%s, %d' % (str(rc), idx))
                # groupchat.unsend_queue.append(fmtcc)  # 也许是这个函数返回值有问题，即使返回错误也可能发送成功。
            idx += 1

        return

    def onRelayMessage(self, msg):
        qDebug('hehee')
        # 汇总消息好友发送过来的消息当作命令处理
        # getqrcode
        # islogined
        # 等待，总之是wxagent支持的命令，

        # self.uicmdHandler(msg)
        self.botcmdHandler(msg)
        return

    def onRelayGroupMessage(self, group_number, message):
        qDebug(('hehee' + str(group_number)).encode())
        groupchat = None
        if group_number in self.toxchatmap:
            groupchat = self.toxchatmap[group_number]
        else:
            qDebug('can not find assoc chatroom')
            return

        qDebug('nextline...')
        print('will send wx msg:%s,%s' % (0, groupchat.ToUser.NickName))
        if groupchat.FromUser is not None:
            print('or will send wx msg:%s,%s' % (0, groupchat.FromUser.NickName))
        else:
            print('or will send wx msg:%s' % (groupchat.FromUserName))

        peer_number = 'jaoijfiwafaewf'
        # TODO 把从各群组来的发给WX端的消息，同步再发送给tox汇总端一份。也就是tox的唯一peer端。
        # TODO 如果是从wx2tox转过去的消息，这里也会再次收到，所以，会向tox汇总端重复发一份了，需要处理。
        try:
            if peer_number == 0: pass  # it myself sent message, omit
            else:
                self.peerRelay.sendMessage(message, self.peerRelay.peer_user)
        except Exception as ex:
            qDebug('send msg error: %s' % str(ex))

        if peer_number == 0:  # it myself sent message, omit
            pass
        else:
            self.sendMessageToWX(groupchat, message)
        return

    def uicmdHandler(self, msg):
        return

    def botcmdHandler(self, msg):
        # 汇总消息好友发送过来的消息当作命令处理
        # getqrcode
        # islogined
        # 等待，总之是wxagent支持的命令，

        #
        cmd = BotCmder.parseCmd(msg)
        if cmd is False:
            qDebug('not a cmd: %s' % msg[0:120])
            return

        if cmd[0] == 'help':
            helpmsg = BotCmder.helpMessage()
            self.peerRelay.sendMessage(helpmsg, self.peerRelay.peer_user)
            return

        elif cmd[0] == 'invite':
            if cmd[1] == '':  # 发送所有的好友，注意是真正的已添加的好友，不是在群组里面的。
                nnlst = self.wxses.getInviteCompleteList()
                self.peerRelay.sendMessage(', '.join(nnlst), self.peerRelay.peer_user)
                pass
            else:
                # 查找是否有该好友，
                # 如果有，则创建与该好友的聊天室
                # 如果没有，则查找是否有前相似匹配的
                # 如果有相似匹配的，则提示相似匹配的所有好友
                nnlst = self.wxses.getInviteCompleteList(cmd[1])
                nnlen = len(nnlst)
                if nnlen == 0:
                    qDebug(('not found:' + cmd[1]).encode())
                elif nnlen == 1:
                    qDebug(('exact match found:' + cmd[1] +',' + str(nnlst[0])).encode())
                    rpstr = 'inviteing %s......' % nnlst[0]
                    self.peerRelay.sendMessage(rpstr, self.peerRelay.peer_user)
                    self.inviteFriendToChat(nnlst[0])
                else:
                    qDebug(('multi match found:' + cmd[1]).encode())
                    self.peerRelay.sendMessage(','.join(nnlst), self.peerRelay.peer_user)
                pass
        else:
            qDebug('unknown cmd:' + str(cmd))

        return

    def startWXBot(self):
        logined = False
        if not self.checkWXLogin():
            qDebug('wxagent not logined.')
        else:
            logined = True
            qDebug('wxagent already logined.')

        ### 无论是否登陆，启动的都发送一次qrcode文件
        qrpic = self.getQRCode()
        if qrpic is None:
            qDebug('maybe wxagent not run...')
            pass
        else:
            fname = self.genQRCodeSaveFileName()
            self.saveContent(fname, qrpic)

            self.qrpic = qrpic
            self.qrfile = fname

            tkc = False
            tkc = self.peerRelay.isConnected()
            if tkc is True:
                url = filestore.upload_file(self.qrpic)
                self.peerRelay.sendMessage('qrcode url:' + url,
                                           self.peerRelay.peer_user)
            else:
                self.need_send_qrfile = True

        if logined is True: self.createWXSession()
        return

    @pyqtSlot(QDBusMessage)
    def onDBusBeginLogin(self, message):
        qDebug(str(message.arguments()))
        # clear smth.
        return


    @pyqtSlot(QDBusMessage)
    def onDBusGotQRCode(self, message):
        args = message.arguments()
        # qDebug(str(message.arguments()))
        qrpic64str = args[1]
        qrpic = QByteArray.fromBase64(qrpic64str.encode())

        self.qrpic = qrpic
        fname = self.genQRCodeSaveFileName()
        self.saveContent(fname, qrpic)
        self.qrfile = fname

        tkc = False
        tkc = self.peerRelay.isConnected()
        if tkc is True:
            url = filestore.upload_file(self.qrpic)
            self.peerRelay.sendMessage('qrpic url:' + url,
                                       self.peerRelay.peer_user)
        else:
            self.need_send_qrfile = True

        return

    @pyqtSlot(QDBusMessage)
    def onDBusLoginSuccess(self, message):
        qDebug(str(message.arguments()))
        self.startWXBot()
        return

    @pyqtSlot(QDBusMessage)
    def onDBusLogined(self, message):
        qDebug(str(message.arguments()))
        return

    @pyqtSlot(QDBusMessage)
    def onDBusLogouted(self, message):
        qDebug(str(message.arguments()))
        return

    @pyqtSlot(QDBusMessage)
    def onDBusNewMessage(self, message):
        # qDebug(str(message.arguments()))
        args = message.arguments()
        msglen = args[0]
        msghcc = args[1]

        if self.wxses is None: self.createWXSession()

        for arg in args:
            if type(arg) == int:
                qDebug(str(type(arg)) + ',' + str(arg))
            else:
                qDebug(str(type(arg)) + ',' + str(arg)[0:120])

        hcc64_str = args[1]
        hcc64 = hcc64_str.encode('utf8')
        hcc = QByteArray.fromBase64(hcc64)

        self.saveContent('msgfromdbus.json', hcc)

        wxmsgvec = WXMessageList()
        wxmsgvec.setMessage(hcc)

        strhcc = hcc.data().decode('utf8')
        qDebug(strhcc[0:120].replace("\n", "\\n"))
        jsobj = json.JSONDecoder().decode(strhcc)

        AddMsgCount = jsobj['AddMsgCount']
        ModContactCount = jsobj['ModContactCount']

        grnames = self.wxproto.parseWebSyncNotifyGroups(hcc)
        self.wxses.addGroupNames(grnames)

        self.wxses.parseModContact(jsobj['ModContactList'])

        msgs = wxmsgvec.getContent()
        for msg in msgs:
            fromUser = self.wxses.getUserByName(msg.FromUserName)
            toUser = self.wxses.getUserByName(msg.ToUserName)
            qDebug(str(fromUser))
            qDebug(str(toUser))

            msg.FromUser = fromUser
            msg.ToUser = toUser

            # pmsg = PlainMessage.fromWXMessage(msg, self.wxses)
            # logstr = pmsg.content
            # xmsg = XmppMessage.fromWXMessage(msg, self.wxses)
            # logstr = xmsg.get()
            umsg = self.peerRelay.unimsgcls.fromWXMessage(msg, self.wxses)
            logstr = umsg.get()

            self.sendMessageToTox(msg, logstr)

            logstr = ''
            # multimedia 消息处理
            if msg.MsgType == WXMsgType.MT_SHOT or msg.MsgType == WXMsgType.MT_X47:
                imgurl = self.getMsgImgUrl(msg)
                logstr += '\n> %s' % imgurl
                self.sendMessageToTox(msg, logstr)
                self.sendShotPicMessageToTox(msg, logstr)
            elif msg.MsgType == WXMsgType.MT_X49:
                if len(msg.MediaId) > 0:
                    fileurl = self.getMsgFileUrl(msg)
                    logstr += '> %s' % fileurl
                    logstr += '\n\nname: %s' % msg.FileName
                    logstr += '\nsize: %s' % msg.FileSize
                else:
                    fileurl = msg.Url
                    logstr += '> %s' % fileurl
                    logstr += '\n\nname: %s' % msg.FileName
                self.sendMessageToTox(msg, logstr)
            elif msg.MsgType == WXMsgType.MT_VOICE:
                logstr += '> voicelen: %s″' % math.floor(msg.VoiceLength/1000)
                self.sendMessageToTox(msg, logstr)
                self.sendVoiceMessageToTox(msg, logstr)

        return

    def sendMessageToTox(self, msg, fmtcc):
        fstatus = self.peerRelay.isPeerConnected(self.peerRelay.peer_user)
        if fstatus is True:
            try:
                # 把收到的消息发送到汇总tox端
                self.peerRelay.sendMessage(fmtcc, self.peerRelay.peer_user)
            except Exception as ex:
                qDebug(b'tox send msg error: ' + str(ex).encode())
            ### dispatch by MsgType
            self.dispatchToToxGroup(msg, fmtcc)
        else:
            # self.wx2tox_msg_buffer.append(msg)
            pass

        return

    def sendShotPicMessageToTox(self, msg, logstr):
        def get_img_reply(data=None):
            if data is None: return
            url = filestore.upload_file(data)
            umsg = 'pic url: ' + url
            self.sendMessageToTox(msg, umsg)
            return

        self.getMsgImgCallback(msg, get_img_reply)
        return

    def sendVoiceMessageToTox(self, msg, logstr):
        def get_voice_reply(data=None):
            if data is None: return
            url = filestore.upload_file(data)
            umsg = 'voice url: ' + url
            self.sendMessageToTox(msg, umsg)
            return

        self.getMsgVoiceCallback(msg, get_voice_reply)
        return

    def dispatchToToxGroup(self, msg, fmtcc):
        groupchat = None

        if msg.FromUserName == 'newsapp':
            qDebug('special chat: newsapp')
            self.dispatchNewsappChatToTox(msg, fmtcc)
            pass
        elif msg.ToUserName == 'filehelper' or msg.FromUserName == 'filehelper':
            qDebug('special chat: filehelper')
            self.dispatchFileHelperChatToTox(msg, fmtcc)
            pass
        elif msg.ToUserName.startswith('@@') or msg.FromUserName.startswith('@@'):
            qDebug('wx group chat:')
            # wx group chat
            self.dispatchWXGroupChatToTox(msg, fmtcc)
            pass
        else:
            qDebug('u2u group chat:')
            # user <=> user
            self.dispatchU2UChatToTox(msg, fmtcc)
            pass

        return

    def dispatchNewsappChatToTox(self, msg, fmtcc):
        groupchat = None
        mkey = None
        title = ''

        mkey = 'newsapp'
        title = 'newsapp@WXU'

        if mkey in self.wxchatmap:
            groupchat = self.wxchatmap[mkey]
            # assert groupchat is not None
            # 有可能groupchat已经就绪，但对方还没有接收请求，这时发送失败，消息会丢失
            number_peers = self.peerRelay.groupNumberPeers(groupchat.group_number)
            if number_peers < 2:
                groupchat.unsend_queue.append(fmtcc)
                ### reinvite peer into group
                self.peerRelay.groupInvite(groupchat.group_number, self.peerRelay.peer_user)
            else:
                self.peerRelay.sendGroupMessage(fmtcc, groupchat.group_number)
        else:
            groupchat = self.createChatroom(msg, mkey, title)
            groupchat.unsend_queue.append(fmtcc)

        return

    def dispatchFileHelperChatToTox(self, msg, fmtcc):
        groupchat = None
        mkey = None
        title = ''

        if msg.FromUserName == 'filehelper':
            mkey = msg.FromUser.cname()
            title = '%s@WXU' % msg.FromUser.NickName
        else:
            mkey = msg.ToUser.cname()
            title = '%s@WXU' % msg.ToUser.NickName

        if mkey in self.wxchatmap:
            groupchat = self.wxchatmap[mkey]
            # assert groupchat is not None
            # 有可能groupchat已经就绪，但对方还没有接收请求，这时发送失败，消息会丢失
            number_peers = self.peerRelay.groupNumberPeers(groupchat.group_number)
            if number_peers < 2:
                groupchat.unsend_queue.append(fmtcc)
                ### reinvite peer into group
                self.peerRelay.groupInvite(groupchat.group_number, self.peerRelay.peer_user)
            else:
                self.peerRelay.sendGroupMessage(fmtcc, groupchat.group_number)
        else:
            groupchat = self.createChatroom(msg, mkey, title)
            groupchat.unsend_queue.append(fmtcc)

        return

    def dispatchWXGroupChatToTox(self, msg, fmtcc):
        groupchat = None
        mkey = None
        title = ''

        if msg.FromUserName.startswith('@@'):
            if msg.FromUser is None:
                # message pending and try get group info
                qDebug('warning FromUser not found, wxgroup not found:' + msg.FromUserName)
                if msg.FromUserName in self.pendingGroupMessages:
                    self.pendingGroupMessages[msg.FromUserName].append([msg, fmtcc])
                else:
                    self.pendingGroupMessages[msg.ToUserName] = list()
                    self.pendingGroupMessages[msg.ToUserName].append([msg, fmtcc])

                self.wxses.addGroupNames([msg.FromUserName])
                QTimer.singleShot(1, self.getBatchGroupAll)
                return
            else:
                mkey = msg.FromUser.cname()
                title = '%s@WXU' % msg.FromUser.NickName
                if len(msg.FromUser.NickName) == 0:
                    qDebug('maybe a temp group and without nickname')
                    title = 'TGC%s@WXU' % msg.FromUser.cname()
        else:
            if msg.ToUser is None:
                qDebug('warning ToUser not found, wxgroup not found:' + msg.ToUserName)
                if msg.FromUserName in self.pendingGroupMessages:
                    self.pendingGroupMessages[msg.ToUserName].append([msg, fmtcc])
                else:
                    self.pendingGroupMessages[msg.ToUserName] = list()
                    self.pendingGroupMessages[msg.ToUserName].append([msg, fmtcc])

                self.wxses.addGroupNames([msg.ToUserName])
                QTimer.singleShot(1, self.getBatchGroupAll)
                return
            else:
                mkey = msg.ToUser.cname()
                title = '%s@WXU' % msg.ToUser.NickName
                if len(msg.ToUser.NickName) == 0:
                    qDebug('maybe a temp group and without nickname')
                    title = 'TGC%s@WXU' % msg.ToUser.cname()

        if mkey in self.wxchatmap:
            groupchat = self.wxchatmap[mkey]
            # assert groupchat is not None
            # 有可能groupchat已经就绪，但对方还没有接收请求，这时发送失败，消息会丢失
            number_peers = self.peerRelay.groupNumberPeers(groupchat.group_number)
            if number_peers < 2:
                groupchat.unsend_queue.append(fmtcc)
                ### reinvite peer into group
                self.peerRelay.groupInvite(groupchat.group_number, self.peerRelay.peer_user)
            else:
                self.peerRelay.sendGroupMessage(fmtcc, groupchat.group_number)
        else:
            # TODO 如果是新创建的groupchat，则要等到groupchat可用再发，否则会丢失消息
            groupchat = self.createChatroom(msg, mkey, title)
            groupchat.unsend_queue.append(fmtcc)

        return

    def dispatchWXGroupChatToTox2(self, msg, fmtcc, GroupUser):
        if msg.FromUser is None: msg.FromUser = GroupUser
        elif msg.ToUser is None: msg.ToUser = GroupUser
        else: qDebug('wtf???...')

        self.dispatchWXGroupChatToTox(msg, fmtcc)
        return

    def dispatchU2UChatToTox(self, msg, fmtcc):
        groupchat = None
        mkey = None
        title = ''

        # 两个用户，正反向通信，使用同一个groupchat，但需要找到它
        # 这两个用户一定有一个是自己
        if self.wxses.me is not None:
            if self.wxses.me.UserName == msg.FromUser.UserName:
                mkey = msg.ToUser.cname()
                title = '%s@WXU' % msg.ToUser.NickName
            if self.wxses.me.UserName == msg.ToUser.UserName:
                mkey = msg.FromUser.cname()
                title = '%s@WXU' % msg.FromUser.NickName
        else:
            qDebug('wtf???')
            assert(self.wxses.me is not None)

        if mkey in self.wxchatmap:
            groupchat = self.wxchatmap[mkey]

        if groupchat is not None:
            # assert groupchat is not None
            # 有可能groupchat已经就绪，但对方还没有接收请求，这时发送失败，消息会丢失
            number_peers = self.peerRelay.groupNumberPeers(groupchat.group_number)
            if number_peers < 2:
                groupchat.unsend_queue.append(fmtcc)
                ### reinvite peer into group
                self.peerRelay.groupInvite(groupchat.group_number, self.peerRelay.peer_user)
            else:
                self.peerRelay.sendGroupMessage(fmtcc, groupchat.group_number)
        else:
            groupchat = self.createChatroom(msg, mkey, title)
            groupchat.unsend_queue.append(fmtcc)

        return

    def createChatroom(self, msg, mkey, title):

        group_number = ('WXU.%s' % mkey).lower()
        group_number = self.peerRelay.createChatroom(mkey, title)
        groupchat = Chatroom()
        groupchat.group_number = group_number
        groupchat.FromUser = msg.FromUser
        groupchat.ToUser = msg.ToUser
        groupchat.FromUserName = msg.FromUserName
        self.wxchatmap[mkey] = groupchat
        self.toxchatmap[group_number] = groupchat
        groupchat.title = title

        self.peerRelay.groupInvite(group_number, self.peerRelay.peer_user)

        return groupchat


    def sendMessageToWX(self, groupchat, mcc):
        qDebug('here')

        FromUser = groupchat.FromUser
        ToUser = groupchat.ToUser

        if ToUser.UserName == 'filehelper' or FromUser.UserName == 'filehelper':
            qDebug('send special chat: filehelper')
            self.sendFileHelperMessageToWX(groupchat, mcc)
            pass
        elif ToUser.UserName.startswith('@@') or FromUser.UserName.startswith('@@'):
            qDebug('send wx group chat:')
            # wx group chat
            self.sendWXGroupChatMessageToWX(groupchat, mcc)
            pass
        else:
            qDebug('send u2u group chat:')
            # user <=> user
            self.sendU2UMessageToWX(groupchat, mcc)
            pass

        # TODO 把从各群组来的发给WX端的消息，再发送给tox汇总端一份。

        if True: return
        from_username = groupchat.FromUser.UserName
        to_username = groupchat.ToUser.UserName
        args = [from_username, to_username, mcc, 1, 'more', 'even more']
        reply = self.sysiface.call('sendmessage', *args)  # 注意把args扩展开

        rr = QDBusReply(reply)
        if rr.isValid():
            qDebug(str(len(rr.value())) + ',' + str(type(rr.value())))
        else:
            qDebug('rpc call error: %s,%s' % (rr.error().name(), rr.error().message()))

        ### TODO send message faild

        return

    def sendFileHelperMessageToWX(self, groupchat, mcc):

        from_username = groupchat.FromUser.UserName
        to_username = groupchat.ToUser.UserName

        qDebug('cc type:, ' + str(type(mcc)))
        qDebug('cc len:, ' + str(len(mcc)))

        try:
            mcc_u8 = mcc.decode('utf8')
            mcc_u16 = mcc_u8.encode('utf16')

            qDebug(mcc_u16)
        except Exception as ex:
            qDebug('str as u8 => u16 error')

        try:
            mcc_u16 = mcc.decode('utf16')
            mcc_u8 = mcc_u16.encode('utf8')

            qDebug(mcc_u8)
        except Exception as ex:
            qDebug('str as u16 => u8 error')

        try:
            qDebug(mcc)
        except Exception as ex:
            qDebug('str as u8 error')

        try:
            bcc = bytes(mcc, 'utf8')
            qDebug(bcc)
        except Exception as ex:
            qDebug('str as bytes u8 error')

        try:
            bcc = bytes(mcc, 'utf8')
            qdebug(bcc)
        except Exception as ex:
            qDebug('str as bytes u8 error')

        # return
        args = [from_username, to_username, mcc, 1, 'more', 'even more']
        reply = self.sysiface.call('sendmessage', *args)  # 注意把args扩展开

        rr = QDBusReply(reply)
        if rr.isValid():
            qDebug(str(rr.value()) + ',' + str(type(rr.value())))
        else:
            qDebug('rpc call error: %s,%s' % (rr.error().name(), rr.error().message()))

        ### TODO send message faild

        return

    def sendWXGroupChatMessageToWX(self, groupchat, mcc):

        from_username = groupchat.FromUser.UserName
        to_username = groupchat.ToUser.UserName

        args = [to_username, from_username, mcc, 1, 'more', 'even more']
        reply = self.sysiface.call('sendmessage', *args)  # 注意把args扩展开

        rr = QDBusReply(reply)
        if rr.isValid():
            qDebug(str(rr.value()) + ',' + str(type(rr.value())))
        else:
            qDebug('rpc call error: %s,%s' % (rr.error().name(), rr.error().message()))

        ### TODO send message faild

        return

    def sendU2UMessageToWX(self, groupchat, mcc):

        from_username = groupchat.FromUser.UserName
        to_username = groupchat.ToUser.UserName

        # 一定是发送给对方的消息
        if self.wxses.me is not None:
            if self.wxses.me.UserName == groupchat.FromUser.UserName:
                from_username = groupchat.FromUser.UserName
                to_username = groupchat.ToUser.UserName
            else:
                from_username = groupchat.ToUser.UserName
                to_username = groupchat.FromUser.UserName
        else:
            qDebug('wtf???')
            assert(self.wxses.me is not None)

        args = [from_username, to_username, mcc, 1, 'more', 'even more']
        reply = self.sysiface.call('sendmessage', *args)  # 注意把args扩展开

        rr = QDBusReply(reply)
        if rr.isValid():
            qDebug(str(rr.value()) + ',' + str(type(rr.value())))
        else:
            qDebug('rpc call error: %s,%s' % (rr.error().name(), rr.error().message()))

        # TODO send message faild

        return

    def createWXSession(self):
        if self.wxses is not None:
            return

        self.wxses = WXSession()

        reply = self.sysiface.call('getinitdata', 123, 'a1', 456)
        rr = QDBusReply(reply)
        # TODO check reply valid

        qDebug(str(len(rr.value())) + ',' + str(type(rr.value())))
        data64 = rr.value().encode('utf8')   # to bytes
        data = QByteArray.fromBase64(data64)
        self.wxses.setInitData(data)
        self.saveContent('initdata.json', data)

        reply = self.sysiface.call('getcontact', 123, 'a1', 456)
        rr = QDBusReply(reply)

        # TODO check reply valid
        qDebug(str(len(rr.value())) + ',' + str(type(rr.value())))
        data64 = rr.value().encode('utf8')   # to bytes
        data = QByteArray.fromBase64(data64)
        self.wxses.setContact(data)
        self.saveContent('contact.json', data)

        reply = self.sysiface.call('getgroups', 123, 'a1', 456)
        rr = QDBusReply(reply)

        # TODO check reply valid
        qDebug(str(len(rr.value())) + ',' + str(type(rr.value())))
        GroupNames = json.JSONDecoder().decode(rr.value())

        self.wxses.addGroupNames(GroupNames)

        QTimer.singleShot(8, self.getBatchGroupAll)
        # QTimer.singleShot(8, self.getBatchContactAll)

        return

    def checkWXLogin(self):
        reply = self.sysiface.call('islogined', 'a0', 123, 'a1')
        qDebug(str(reply))
        rr = QDBusReply(reply)

        if not rr.isValid(): return False
        qDebug(str(rr.value()) + ',' + str(type(rr.value())))
        if rr.value() is False:
            return False

        return True

    def getQRCode(self):
        reply = self.sysiface.call('getqrpic', 123, 'a1', 456)
        rr = QDBusReply(reply)

        if not rr.isValid(): return None

        qDebug(str(len(rr.value())) + ',' + str(type(rr.value())))
        qrpic64 = rr.value().encode('utf8')   # to bytes
        qrpic = QByteArray.fromBase64(qrpic64)

        return qrpic

    def genQRCodeSaveFileName(self):
        now = QDateTime.currentDateTime()
        fname = '/tmp/wxqrcode_%s.jpg' % now.toString('yyyyMMddHHmmsszzz')
        return fname

    # @param data QByteArray | bytes
    def genMsgImgSaveFileName(self, data):
        now = QDateTime.currentDateTime()

        m = magic.open(magic.MAGIC_MIME_TYPE)
        m.load()
        mty = m.buffer(data.data()) if type(data) == QByteArray else m.buffer(data)
        m.close()

        suffix = mty.split('/')[1]
        suffix = 'jpg' if suffix == 'jpeg' else suffix
        suffix = 'bmp' if suffix == 'x-ms-bmp' else suffix

        fname = '/tmp/wxpic_%s.%s' % (now.toString('yyyyMMddHHmmsszzz'), suffix)
        return fname

    def getBaseFileName(self, fname):
        bfname = QFileInfo(fname).fileName()
        return bfname

    def getGroupsFromDBus(self):

        reply = self.sysiface.call('getgroups', 123, 'a1', 456)
        rr = QDBusReply(reply)

        # TODO check reply valid
        qDebug(str(len(rr.value())) + ',' + str(type(rr.value())))
        GroupNames = json.JSONDecoder().decode(rr.value())

        return GroupNames

    def getBatchGroupAll(self):
        groups2 = self.getGroupsFromDBus()
        self.wxses.addGroupNames(groups2)
        groups = self.wxses.getICGroups()
        qDebug(str(groups))

        reqcnt = 0
        arg0 = []
        for grname in groups:
             melem = {'UserName': grname, 'ChatRoomId': ''}
             arg0.append(melem)

        argjs = json.JSONEncoder().encode(arg0)
        pcall = self.sysiface.asyncCall('getbatchcontact', argjs)
        watcher = QDBusPendingCallWatcher(pcall)
        # watcher.finished.connect(self.onGetBatchContactDone)
        watcher.finished.connect(self.onGetBatchGroupDone)
        self.asyncWatchers[watcher] = arg0
        reqcnt += 1

        qDebug('async reqcnt: ' + str(reqcnt))

        return

    # @param watcher QDBusPengindCallWatcher
    def onGetBatchGroupDone(self, watcher):
        pendReply = QDBusPendingReply(watcher)
        qDebug(str(watcher))
        qDebug(str(pendReply.isValid()))
        if pendReply.isValid():
            hcc = pendReply.argumentAt(0)
            qDebug(str(type(hcc)))
        else:
            hcc = pendReply.argumentAt(0)
            qDebug(str(len(hcc)))
            qDebug(str(hcc))
            return

        message = pendReply.reply()
        args = message.arguments()
        # qDebug(str(len(args)))

        hcc = args[0]  # QByteArray
        strhcc = self.hcc2str(hcc)
        hccjs = json.JSONDecoder().decode(strhcc)

        # print(strhcc)
        # self.saveContent('groups.json', hcc)

        memcnt = 0
        for contact in hccjs['ContactList']:
            memcnt += 1
            # print(contact)
            # self.wxses.addMember(contact)
            grname = contact['UserName']
            if not WXUser.isGroup(grname): continue

            print('uid=%s,un=%s,nn=%s\n' % (0, contact['UserName'], contact['NickName']))
            self.wxses.addGroupUser(grname, contact)
            if grname in self.pendingGroupMessages and len(self.pendingGroupMessages[grname]) > 0:
                while len(self.pendingGroupMessages[grname]) > 0:
                    msgobj = self.pendingGroupMessages[grname].pop()
                    GroupUser = self.wxses.getGroupByName(grname)
                    if GroupUser is None:
                        qDebug('still not get msg group info, new?sink?')
                    else:
                        # 是不是能说明，可以把该grname从半完成状态，设置为完成状态呢？
                        self.dispatchWXGroupChatToTox2(msgobj[0], msgobj[1], GroupUser)

        qDebug('got memcnt: %s/%s' % (memcnt, len(self.wxses.ICGroups)))

        # flow next
        QTimer.singleShot(32, self.getBatchContactAll)

        return

    def getBatchContactAll(self):

        groups = self.wxses.getICGroups()
        qDebug(str(groups))
        reqcnt = 0
        for grname in groups:
            members = self.wxses.getGroupMembers(grname)
            qDebug('prepare get group member info: %s, %s' % (grname, len(members)))
            arg0 = []
            for member in members:
                melem = {'UserName': member, 'EncryChatRoomId': grname}
                arg0.append(melem)

            cntpertime = 50
            while len(arg0) > 0:
                subarg = arg0[0:cntpertime]
                subargjs = json.JSONEncoder().encode(subarg)
                pcall = self.sysiface.asyncCall('getbatchcontact', subargjs)
                watcher = QDBusPendingCallWatcher(pcall)
                watcher.finished.connect(self.onGetBatchContactDone)
                self.asyncWatchers[watcher] = subarg
                arg0 = arg0[cntpertime:]
                reqcnt += 1
                # break
            # break

        qDebug('async reqcnt: ' + str(reqcnt))

        return

    # @param message QDBusPengindCallWatcher
    def onGetBatchContactDone(self, watcher):
        pendReply = QDBusPendingReply(watcher)
        qDebug(str(watcher))
        qDebug(str(pendReply.isValid()))
        if pendReply.isValid():
            hcc = pendReply.argumentAt(0)
            qDebug(str(type(hcc)))
        else:
            return

        message = pendReply.reply()
        args = message.arguments()
        # qDebug(str(len(args)))

        hcc = args[0]  # QByteArray
        strhcc = self.hcc2str(hcc)
        hccjs = json.JSONDecoder().decode(strhcc)

        # qDebug(str(self.wxses.getGroups()))
        qDebug('next linee...............')
        # print(strhcc)

        memcnt = 0
        for contact in hccjs['ContactList']:
            memcnt += 1
            # print(contact)
            self.wxses.addMember(contact)

        qDebug('got memcnt: %s/%s(left)' % (memcnt, len(self.wxses.ICUsers)))
        if len(self.wxses.ICUsers) == 0:
            self.wxses.checkUncompleteUsers()

        return

    # @param cb(data)
    def getMsgImgCallback(self, msg, imgcb=None):

        def on_dbus_reply(watcher):
            qDebug('replyyyyyyyyyyyyyyy')
            pendReply = QDBusPendingReply(watcher)
            qDebug(str(watcher))
            qDebug(str(pendReply.isValid()))
            if pendReply.isValid():
                hcc = pendReply.argumentAt(0)
                qDebug(str(type(hcc)))
            else:
                self.asyncWatchers.pop(watcher)
                if imgcb is not None: imgcb(None)
                return

            message = pendReply.reply()
            args = message.arguments()

            self.asyncWatchers.pop(watcher)
            # send img file to tox client
            if imgcb is not None: imgcb(args[0])

            return

        args = [msg.MsgId, False]
        pcall = self.sysiface.asyncCall('get_msg_img', *args)
        watcher = QDBusPendingCallWatcher(pcall)
        watcher.finished.connect(on_dbus_reply)
        self.asyncWatchers[watcher] = '1'

        return

    def getMsgImgUrl(self, msg):
        args = [msg.MsgId, False]
        return self.syncGetRpc('get_msg_img_url', args)

    def getMsgFileUrl(self, msg):
        file_name = msg.FileName.replace(' ', '+')
        args = [msg.FromUserName, msg.MediaId, file_name, 0]
        return self.syncGetRpc('get_msg_file_url', args)

    # @param cb(data)
    def getMsgVoiceCallback(self, msg, imgcb=None):

        def on_dbus_reply(watcher):
            qDebug('replyyyyyyyyyyyyyyy')
            pendReply = QDBusPendingReply(watcher)
            qDebug(str(watcher))
            qDebug(str(pendReply.isValid()))
            if pendReply.isValid():
                hcc = pendReply.argumentAt(0)
                qDebug(str(type(hcc)))
            else:
                self.asyncWatchers.pop(watcher)
                if imgcb is not None: imgcb(None)
                return

            message = pendReply.reply()
            args = message.arguments()

            self.asyncWatchers.pop(watcher)
            # send img file to tox client
            if imgcb is not None: imgcb(args[0])

            return

        args = [msg.MsgId]
        pcall = self.sysiface.asyncCall('get_msg_voice', *args)
        watcher = QDBusPendingCallWatcher(pcall)
        watcher.finished.connect(on_dbus_reply)
        self.asyncWatchers[watcher] = '1'

        return

    # @param name str
    # @param args list
    # @param return None | mixed
    def syncGetRpc(self, name, args):
        reply = self.sysiface.call(name, *args)
        rr = QDBusReply(reply)

        # TODO check reply valid
        qDebug(name + ':' + str(len(rr.value())) + ',' + str(type(rr.value())))
        if rr.isValid():
            return rr.value()
        return None

    # TODO 合并抽象该方法与createChatroom方法
    # @param nick str 好友的NickName
    def inviteFriendToChat(self, nick):

        FromUser = self.wxses.me
        ToUser = self.wxses.getUserByNickName(nick)
        title = '%s@WXU' % nick
        mkey = ToUser.cname()

        group_number = ('WXU.%s' % mkey).lower()
        group_number = self.peerRelay.createChatroom(mkey, title)
        groupchat = Chatroom()
        groupchat.group_number = group_number
        groupchat.FromUser = FromUser
        groupchat.ToUser = ToUser
        groupchat.FromUserName = FromUser.UserName
        groupchat.title = title

        self.wxchatmap[mkey] = groupchat
        self.toxchatmap[group_number] = groupchat

        self.peerRelay.groupInvite(group_number, self.peerRelay.peer_user)

        return groupchat

    # @param hcc QByteArray
    # @return str
    def hcc2str(self, hcc):
        strhcc = ''

        try:
            astr = hcc.data().decode('gkb')
            qDebug(astr[0:120].replace("\n", "\\n"))
            strhcc = astr
        except Exception as ex:
            qDebug('decode gbk error:')

        try:
            astr = hcc.data().decode('utf16')
            qDebug(astr[0:120].replace("\n", "\\n"))
            strhcc = astr
        except Exception as ex:
            qDebug('decode utf16 error:')

        try:
            astr = hcc.data().decode('utf8')
            qDebug(astr[0:120].replace("\n", "\\n"))
            strhcc = astr
        except Exception as ex:
            qDebug('decode utf8 error:')

        return strhcc


    # @param name str
    # @param hcc QByteArray
    # @return None
    def saveContent(self, name, hcc):
        # fp = QFile("baseinfo.json")
        fp = QFile(name)
        fp.open(QIODevice.ReadWrite | QIODevice.Truncate)
        # fp.resize(0)
        fp.write(hcc)
        fp.close()

        return


# hot fix
g_w2t = None


def on_app_about_close():
    qDebug('hereee')
    global g_w2t

    g_w2t.peerRelay.disconnectIt()
    return


def main():
    app = QCoreApplication(sys.argv)
    import wxagent.qtutil as qtutil
    qtutil.pyctrl()

    w2t = WX2Tox()

    global g_w2t
    g_w2t = w2t
    app.aboutToQuit.connect(on_app_about_close)

    app.exec_()
    return


if __name__ == '__main__': main()



