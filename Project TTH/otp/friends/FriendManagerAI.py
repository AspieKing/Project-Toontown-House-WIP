from direct.directnotify import DirectNotifyGlobal
from direct.distributed.DistributedObjectAI import DistributedObjectAI
from otp.ai.MagicWordGlobal import *
from otp.otpbase import OTPGlobals

from datetime import datetime
import random

neverDeleteSecrets = ['sto dev']
class FriendManagerAI(DistributedObjectAI):
    notify = DirectNotifyGlobal.directNotify.newCategory("FriendManagerAI")
    
    def __init__(self, air):
        DistributedObjectAI.__init__(self, air)
        self.air = air
        self.currentContext = 0
        self.requests = {}
        self.tfCodes = {}
        taskMgr.add(self.__tfCodesTask, 'TrueFriendsCodesClearTask')
        self.tfCodes['sto dev'] = (100000025,7)

    def friendQuery(self, requested):
        avId = self.air.getAvatarIdFromSender()
        if not requested in self.air.doId2do:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to friend a player that does not exist!')
            return
        context = self.currentContext
        self.requests[context] = [ [ avId, requested ], 'friendQuery']
        self.currentContext += 1
        self.sendUpdateToAvatarId(requested, 'inviteeFriendQuery', [avId, self.air.doId2do[avId].getName(), self.air.doId2do[avId].getDNAString(), context])

    def cancelFriendQuery(self, context):
        avId = self.air.getAvatarIdFromSender()
        if not context in self.requests:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to cancel a request that doesn\'t exist!')
            return
        if avId != self.requests[context][0][0]:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to cancel someone elses request!')
            return
        self.requests[context][1] = 'cancelled'
        self.sendUpdateToAvatarId(self.requests[context][0][1], 'inviteeCancelFriendQuery', [context])

    def inviteeFriendConsidering(self, yesNo, context):
        avId = self.air.getAvatarIdFromSender()
        if not context in self.requests:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to consider a friend request that doesn\'t exist!')
            return
        if avId != self.requests[context][0][1]:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to consider for someone else!')
            return
        if self.requests[context][1] != 'friendQuery':
            self.air.writeServerEvent('suspicious', avId, 'Player tried to reconsider friend request!')
            return
        if yesNo != 1:
            self.sendUpdateToAvatarId(self.requests[context][0][0], 'friendConsidering', [yesNo, context])
            del self.requests[context]
            return
        self.requests[context][1] = 'friendConsidering'
        self.sendUpdateToAvatarId(self.requests[context][0][0], 'friendConsidering', [yesNo, context])

    def inviteeFriendResponse(self, response, context):
        avId = self.air.getAvatarIdFromSender()
        if not context in self.requests:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to respond to a friend request that doesn\'t exist!')
            return
        if avId != self.requests[context][0][1]:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to respond to someone else\'s request!')
            return
        if self.requests[context][1] == 'cancelled':
            self.air.writeServerEvent('suspicious', avId, 'Player tried to respond to non-active friend request!')
            return
        self.sendUpdateToAvatarId(self.requests[context][0][0], 'friendResponse', [response, context])
        if response == 1:
            requested = self.air.doId2do[self.requests[context][0][1]]
            requester = self.air.doId2do[self.requests[context][0][0]]
            
            requested.extendFriendsList(requester.getDoId(), 0)
            requester.extendFriendsList(requested.getDoId(), 0)
            
            requested.d_setFriendsList(requested.getFriendsList())
            requester.d_setFriendsList(requester.getFriendsList())
        del self.requests[context]


    def inviteeAcknowledgeCancel(self, context):
        avId = self.air.getAvatarIdFromSender()
        if not context in self.requests:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to acknowledge the cancel of a friend request that doesn\'t exist!')
            return
        if avId != self.requests[context][0][1]:
            self.air.writeServerEvent('suspicious', avId, 'Player tried to acknowledge someone else\'s cancel!')
            return
        if self.requests[context][1] != 'cancelled':
            self.air.writeServerEvent('suspicious', avId, 'Player tried to cancel non-cancelled request!')
            return
        del self.requests[context]


    def friendConsidering(self, todo0, todo1):
        pass

    def friendResponse(self, todo0, todo1):
        pass

    def inviteeFriendQuery(self, todo0, todo1, todo2, todo3):
        pass

    def inviteeCancelFriendQuery(self, todo0):
        pass

    def requestSecret(self):
        avId = self.air.getAvatarIdFromSender()
        av = self.air.doId2do.get(avId)
        if len(av.getFriendsList()) == OTPGlobals.MaxFriends:
            self.requestSecretResponse(0, '')
        else:
            day = datetime.now().day
            code = self.generateTrueFriendsCode()
            self.tfCodes[code] = (avId, day)
            self.requestSecretResponse(1, code)
            print code
        
    def generateTrueFriendsCode(self):
        chars = ['a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p','q','r','s','t','u','v','w','x','y','z','0','1','2','3','4','5','6','7','8','9']
        def r(): return random.choice(chars)
        code = '%s%s%s %s%s%s' %(r(),r(),r(),r(),r(),r())
        return code

    def requestSecretResponse(self, result, secret):
        avId = self.air.getAvatarIdFromSender()
        self.sendUpdateToAvatarId(avId, 'requestSecretResponse', [result, secret])

    def submitSecret(self, secret):
        productPrefix = OTPGlobals.getDefaultProductPrefix()
        print secret
        if not self.tfCodes.has_key(secret):
            self.submitSecretResponse(0, 0)
            return
        secretInfo = self.tfCodes[secret]
        avId = self.air.getAvatarIdFromSender()
        av = self.air.doId2do.get(avId)
        friendAvId = secretInfo[0]
        friendAv = self.air.doId2do.get(friendAvId)
        if av:
            if friendAv:
                if avId == friendAvId:
                    self.submitSecretResponse(3, 0)
                    self.removeSecret(secret)
                    return
                elif len(friendAv.getFriendsList()) == OTPGlobals.MaxFriends or len(av.getFriendsList()) == OTPGlobals.MaxFriends:
                    self.submitSecretResponse(2, friendAvId)
                    return
                else:
                    friendAv.extendFriendsList(av.getDoId(), 1)
                    friendAv.d_setFriendsList(friendAv.getFriendsList())
                    av.extendFriendsList(friendAvId, 1)
                    av.d_setFriendsList(av.getFriendsList())
                    self.submitSecretResponse(1, friendAvId)
                    self.removeSecret(secret)
                    return
            else: 
                # Friend is offline!
                def handleQuery(dclass, fields):
                    if dclass != self.air.dclassesByName['DistributedToonAI']:
                        return
                    newFriendsList = []
                    oldFriendsList = fields['setFriendsList'][0]
                    if len(oldFriendsList) == OTPGlobals.MaxFriends:
                        self.submitSecretResponse(2, friendAvId)
                        return
                        
                    for friend in oldFriendsList: newFriendsList.append(friend)
                    newFriendsList.append((avId, 1))
                    self.air.dbInterface.updateObject(self.air.dbId, friendAvId, self.air.dclassesByName['DistributedToonAI'],
                                                  {'setFriendsList' : [newFriendsList]})
                    av.extendFriendsList(friendAvId, 1)
                    av.d_setFriendsList(av.getFriendsList())
                    self.submitSecretResponse(1, friendAvId)
                    self.removeSecret(secret)
                    
                self.air.dbInterface.queryObject(self.air.dbId, friendAvId, handleQuery)
                
    def removeSecret(self, secret):
        if self.tfCodes.has_key(secret):
            if secret not in neverDeleteSecrets:
                self.tfCodes.pop(secret)

    def submitSecretResponse(self, result, avId):
        avId = self.air.getAvatarIdFromSender()
        self.sendUpdateToAvatarId(avId, 'submitSecretResponse', [result, avId])
        
    def __tfCodesTask(self, task):
        for code in self.tfCodes.keys():
            codeInfo = self.tfCodes[code]
            codeDay = codeInfo[1]
            today = datetime.now().day
            if codeDay + 2 == today:
                self.notify.info('Removing 2 days secret: %s' %code)
                self.tfCodes.pop(code)
                
        return task.again

@magicWord(category=CATEGORY_CHEAT, types=[int], access=1000)
def tf():
    admin = spellbook.getInvoker()
    av = spellbook.getTarget()
    
    if admin == av:
        return "Cannot tf yourself!"
    
    admin.extendFriendsList(av.getDoId(), 1)
    av.extendFriendsList(admin.getDoId(), 1)
    
    admin.d_setFriendsList(admin.getFriendsList())
    av.d_setFriendsList(av.getFriendsList())
