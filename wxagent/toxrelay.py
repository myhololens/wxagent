# toxcore protocol IM relay class

import logging
from collections import defaultdict

from PyQt5.QtCore import *

from .qtoxkit import *

from .imrelay import IMRelay
from .unimessage import ToxMessage


class ToxRelay(IMRelay):

    def __init__(self, parent=None):
        super(ToxRelay, self).__init__(parent)

        self.unimsgcls = ToxMessage
        self.src_pname = ''

        self.self_user = ''
        self.peer_user = ''
        self.nick_name = ''

        self.toxkit = None  # QToxKit

        self.initToxnet()
        return

    # abstract method implemention
    # @return True|False
    def sendMessage(self, msg, peer):
        try:
            self.toxkit.sendMessage(peer, msg)
        except Exception as ex:
            qDebug(str(ex))
            return False
        return True

    # @return True|False
    def sendGroupMessage(self, msg, peer):
        group_number = int(peer)
        rc = self.toxkit.groupchatSendMessage(group_number, msg)
        return rc

    # @return True|False
    def sendFileMessage(self, msg, peer):
        return

    # @return True|False
    def sendVoiceMessage(self, msg, peer):
        return

    # @return True|False
    def sendImageMessage(self, msg, peer):
        return

    def disconnectIt(self):
        return

    def isConnected(self):
        status = self.toxkit.selfGetConnectionStatus()
        return status > 0

    def isPeerConnected(self, peer):
        # qDebug(str(self.fixstatus))
        status = self.toxkit.friendGetConnectionStatus(peer)
        return status > 0

    def createChatroom(self, room_key, title):
        group_number = self.toxkit.groupchatAdd()
        rc = self.toxkit.groupchatSetTitle(group_number, title)

        # 上游需要一个字符串类型的group_number标识
        # 注意在传递回来的地方，要再转换成int
        return str(group_number)

    def groupInvite(self, group_number, peer):
        group_number = int(group_number)
        rc = self.toxkit.groupchatInviteFriend(group_number, peer)
        return rc

    def groupNumberPeers(self, group_number):
        group_number = int(group_number)
        number_peers = self.toxkit.groupNumberPeers(group_number)
        return number_peers

    # raw toxcore protocol handler
    def initToxnet(self):
        from .secfg import peer_tox_user
        self.peer_user = peer_tox_user

        loglevel = logging.DEBUG
        loglevel = logging.WARNING
        logging.basicConfig(level=loglevel, format='%(levelname)-8s %(message)s')

        self.nick_name = 'yatbot0inmuc'
        self.is_connected = False
        self.fixrooms = defaultdict(list)
        self.fixstatus = defaultdict(bool)

        qDebug('hrehhrere')
        ident = 'qq2tox'
        self.toxkit = QToxKit(ident, True)
        self.toxkit.connectChanged.connect(self.onToxnetConnectStatus, Qt.QueuedConnection)
        self.toxkit.newMessage.connect(self.onToxnetMessage, Qt.QueuedConnection)
        self.toxkit.friendConnectionStatus.connect(self.onToxnetFriendStatus, Qt.QueuedConnection)
        self.toxkit.fileChunkRequest.connect(self.onToxnetFileChunkReuqest, Qt.QueuedConnection)
        self.toxkit.fileRecvControl.connect(self.onToxnetFileRecvControl, Qt.QueuedConnection)
        self.toxkit.newGroupMessage.connect(self.onToxnetGroupMessage, Qt.QueuedConnection)
        self.toxkit.groupNamelistChanged.connect(self.onToxnetGroupNamelistChanged, Qt.QueuedConnection)

        return

    def onToxnetConnectStatus(self, status):
        qDebug(str(status))

        if status > 0:
            self.connected.emit()
        else:
            self.disconnected.emit()

        friendId = self.peer_user
        fexists = self.toxkit.friendExists(friendId)
        qDebug(str(fexists))

        famsg = 'from qq2tox...'
        if not fexists:
            friend_number = self.toxkit.friendAdd(friendId, famsg)
            qDebug(str(friend_number))
        else:
            # rc = self.toxkit.friendDelete(friendId)
            # qDebug(str(rc))
            try:
                True
                # friend_number = self.toxkit.friendAddNorequest(friendId)
                # qDebug(str(friend_number))
            except Exception as ex:
                pass
            # self.toxkit.friendAddNorequest(friendId)
            pass

        return

    def onToxnetMessage(self, friendId, msgtype, msg):
        qDebug(friendId + ':' + str(msgtype) + '=' + str(len(msg)))

        # 汇总消息好友发送过来的消息当作命令处理
        # getqrcode
        # islogined
        # 等待，总之是wxagent支持的命令，

        self.newMessage.emit(msg)

        return

    def onToxnetFriendStatus(self, friendId, status):
        qDebug(friendId + ':' + str(status))

        if status > 0:
            self.peerConnected.emit(friendId)
        else:
            self.peerDisconnected.emit(friendId)

        return

    def onToxnetFileChunkReuqest(self, friendId, file_number, position, length):
        if qrand() % 7 == 1:
            qDebug('fn=%s,pos=%s,len=%s' % (file_number, position, length))

        if position >= len(self.qrpic):
            qDebug('warning exceed file size: finished.')
            # self.toxkit.fileControl(friendId, file_number, 2)  # CANCEL
            return

        chunk = self.qrpic[position:(position + length)]
        self.toxkit.fileSendChunk(friendId, file_number, position, chunk)
        return

    def onToxnetFileRecvControl(self, friendId, file_number, control):
        qDebug('fn=%s,ctl=%s,' % (file_number, control))

        return

    def onToxnetGroupMessage(self, group_number, peer_number, message):
        qDebug('nextline...')
        print('gn=%s,pn=%s,mlen=%s,mp=%s' %
              (group_number, peer_number, len(message), message[0:27]))

        if peer_number == 0:  # it myself sent message, omit
            return

        str_group_number = str(group_number)
        self.newGroupMessage.emit(str_group_number, message)
        return

    def onToxnetGroupNamelistChanged(self, group_number, peer_number, change):
        qDebug(str(change))

        # TODO group number count == 2
        number_peers = self.toxkit.groupNumberPeers(group_number)
        if number_peers == 0:
            qDebug('why 0?')
        elif number_peers == 1:
            qDebug('myself added')
        elif number_peers == 2:
            qDebug('toxpeer added')
        else:
            qDebug('who is there? wtf?')

        qDebug('np: %d' % number_peers)
        if number_peers != 2: return

        # 上游需要字符串类型的group标识。
        self.peerEnterGroup.emit(str(group_number))
        return
