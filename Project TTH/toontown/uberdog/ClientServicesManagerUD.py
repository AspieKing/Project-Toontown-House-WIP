from direct.distributed.DistributedObjectGlobalUD import DistributedObjectGlobalUD
from direct.distributed.PyDatagramIterator import *
from direct.directnotify.DirectNotifyGlobal import directNotify
from direct.fsm.FSM import FSM
from direct.distributed.PyDatagram import *
from toontown.toon.ToonDNA import ToonDNA
from toontown.toon.Experience import Experience
from toontown.makeatoon.NameGenerator import NameGenerator
from toontown.makeatoon.NamePattern import NamePattern
from toontown.toonbase import TTLocalizer
import anydbm
import time
import urllib
import urllib2
import hashlib

NAME_APPROVED = 'apr'
NAME_REJECTED = 'rej'
NAME_PENDING = 'pen'
    
def isNamePattern(dgi, namePattern, gender):        
    try:
        typed = dgi.getUint8()
        if typed:
            if not dgi.getRemainingSize():
                return 0, None
        
            return 0, dgi.getString()
        
        if dgi.getRemainingSize() != 8:
            return 0, None
  
        nameIndices = [dgi.getInt16() for _ in xrange(4)]
        name = namePattern.getStringFromIndexes(gender, nameIndices)
    
        return 1, name
        
    except:
        return 0, name
    
class LocalAccountDB:
    DEFAULT_ACCESS_LEVEL = 500
    def __init__(self, csm):
        self.csm = csm

        # This uses dbm, so we open the DB file:
        filename = simbase.config.GetString('accountdb-local-file',
                                            'dev-accounts.db')
        self.dbm = anydbm.open(filename, 'c')

    def lookup(self, cookie, callback):
        # See if the cookie is in the DBM:
        if cookie in self.dbm:
            # Return it w/ account ID!
            callback({'success': True,
                      'accountId': int(self.dbm[cookie]),
                      'databaseId': cookie})
                      
        else:
            # Nope, let's return w/o account ID:
            callback({'success': True,
                      'accountId': 0,
                      'databaseId': cookie,
                      'adminAccess': self.DEFAULT_ACCESS_LEVEL})

    def storeAccountID(self, databaseId, accountId, callback):
        self.dbm[databaseId] = str(accountId)
        if getattr(self.dbm, 'sync', None):
            self.dbm.sync()
        callback()
        
    def handlePostNameRequest(self, doId, wantedName):
        pass
        
    def getNameStatus(self, doId, callback):
        callback(NAME_APPROVED)
        
class ServerAccountDB(LocalAccountDB):
    """
    Acts like a gateway between the local database and the server, translating tokens into username
    """
    DEFAULT_ACCESS_LEVEL = 0
    loginUrl = config.GetString('account-db-login-url', 'https://api.toontownhouse.net/api_login.php')
    namesUrl = config.GetString('account-db-name-url', 'https://api.toontownhouse.net/names.php')
    ERRORS = ['.err1', '.err2', '.err3']
    
    def post(self, url, data = {}):
        headers = {'User-Agent' : 'UberAgent'}
        data["anticacheagent"] = str(id(data) + id(url))
        data = urllib.urlencode(data)
        
        req = urllib2.Request(url, data, headers)
        try: response = urllib2.urlopen(req)
        except: return ".err4"
        return response.read()
        
    def lookup(self, cookie, callback):
        result = self.post(self.loginUrl, {"token": cookie})
        
        if not result or result in self.ERRORS:
            callback({'success': False,
                      'reason': 'The server rejected the token!'})
            return
                    
        LocalAccountDB.lookup(self, result, callback)
        
    def handlePostNameRequest(self, doId, wantedName):
        data = {}
        data["key"] = simbase.air.getApiKey()
        data["avId"] = doId
        data["wantedName"] = wantedName
        data["operation"] = "set"
        self.post(self.namesUrl, data)
        
    def getNameStatus(self, avId, callback):
        data = {}
        data["key"] = simbase.air.getApiKey()
        data["avId"] = avId
        data["operation"] = "get"
        ret = self.post(self.namesUrl, data)
        if ret not in (NAME_APPROVED, NAME_PENDING, NAME_REJECTED):
            ret = NAME_PENDING
            
        callback(ret)
        
class TrapDoorAccountDB(ServerAccountDB):
    """ Bans all accounts that try to login (could be useful in case of hacking) """
    """ Incomplete at the moment """
    def lookup(self, cookie, callback):
        result = self.post(self.loginUrl, {"token": cookie})
        
        if not result or result in self.ERRORS:
            callback({'success': False,
                      'reason': 'The server rejected the token!'})
            return
            
        print 'Trap door: Banning', result
        # to do: ban
        callback({'success': False, 'reason': 'Trapdoor'})

class OperationFSM(FSM):
    TARGET_CONNECTION = False

    def __init__(self, csm, target):
        self.csm = csm
        self.target = target
        FSM.__init__(self, self.__class__.__name__)

    def enterKill(self, reason=''):
        if self.TARGET_CONNECTION:
            self.csm.killConnection(self.target, reason)
        else:
            self.csm.killAccount(self.target, reason)
        self.demand('Off')

    def enterOff(self):
        if self.TARGET_CONNECTION:
            del self.csm.connection2fsm[self.target]
        else:
            del self.csm.account2fsm[self.target]

class LoginAccountFSM(OperationFSM):
    TARGET_CONNECTION = True
    notify = directNotify.newCategory('LoginAccountFSM')

    def enterStart(self, cookie):
        self.cookie = cookie

        self.demand('QueryAccountDB')

    def enterQueryAccountDB(self):
        self.csm.accountDB.lookup(self.cookie, self.__handleLookup)

    def __handleLookup(self, result):
        if not result.get('success'):
            self.csm.air.writeServerEvent('cookieRejected', self.target, self.cookie)
            self.demand('Kill', result.get('reason', 'The accounts database rejected your cookie.'))
            return

        self.databaseId = result.get('databaseId', 0)
        accountId = result.get('accountId', 0)
        self.adminAccess = result.get('adminAccess', -1)
        self.username = result.get('username', '')
        if accountId:
            self.accountId = accountId
            self.demand('RetrieveAccount')
        else:
            self.demand('CreateAccount')

    def enterRetrieveAccount(self):
        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.accountId,
                                             self.__handleRetrieve)

    def __handleRetrieve(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['AccountUD']:
            self.demand('Kill', 'Your account object was not found in the database!')
            return

        self.account = fields
        self.demand('SetAccount')

    def enterCreateAccount(self):
        self.account = {'ACCOUNT_AV_SET': [0]*6,
                        'pirateAvatars': [],
                        'ESTATE_ID': 0,
                        'ACCOUNT_AV_SET_DEL': [],
                        'CREATED': time.ctime(),
                        'LAST_LOGIN': time.ctime(),
                        'ACCOUNT_ID': str(self.databaseId),
                        'ADMIN_ACCESS': self.adminAccess}

        self.csm.air.dbInterface.createObject(
            self.csm.air.dbId,
            self.csm.air.dclassesByName['AccountUD'],
            self.account,
            self.__handleCreate)

    def __handleCreate(self, accountId):
        if self.state != 'CreateAccount':
            self.notify.warning('Received create account response outside of CreateAccount state.')
            return

        if not accountId:
            self.notify.warning('Database failed to construct an account object!')
            self.demand('Kill', 'Your account object could not be created in the game database.')
            return

        self.csm.air.writeServerEvent('accountCreated', accountId)

        self.accountId = accountId
        self.demand('StoreAccountID')

    def enterStoreAccountID(self):
        self.csm.accountDB.storeAccountID(self.databaseId, self.accountId, self.__handleStored)

    def __handleStored(self, success=True):
        if not success:
            self.demand('Kill', 'The account server could not save your account DB ID!')
            return

        self.demand('SetAccount')

    def enterSetAccount(self):
        # First, if there's anybody on the account, kill 'em for redundant login:
        dg = PyDatagram()
        dg.addServerHeader(self.csm.GetAccountConnectionChannel(self.accountId),
                           self.csm.air.ourChannel, CLIENTAGENT_EJECT)
        dg.addUint16(100)
        dg.addString('This account has been logged in elsewhere.')
        self.csm.air.send(dg)

        # Next, add this connection to the account channel.
        dg = PyDatagram()
        dg.addServerHeader(self.target, self.csm.air.ourChannel, CLIENTAGENT_OPEN_CHANNEL)
        dg.addChannel(self.csm.GetAccountConnectionChannel(self.accountId))
        self.csm.air.send(dg)

        # Now set their sender channel to represent their account affiliation:
        dg = PyDatagram()
        dg.addServerHeader(self.target, self.csm.air.ourChannel, CLIENTAGENT_SET_CLIENT_ID)
        dg.addChannel(self.accountId << 32) # accountId in high 32 bits, 0 in low (no avatar)
        self.csm.air.send(dg)

        # Un-sandbox them!
        dg = PyDatagram()
        dg.addServerHeader(self.target, self.csm.air.ourChannel, CLIENTAGENT_SET_STATE)
        dg.addUint16(2) # ESTABLISHED state.
        self.csm.air.send(dg)

        fields = {'LAST_LOGIN': time.ctime(), 'ACCOUNT_ID': str(self.databaseId)}
        
        if self.adminAccess != -1:
            fields.update({'ADMIN_ACCESS': self.adminAccess})
            
        # Update the last login timestamp:
        self.csm.air.dbInterface.updateObject(
            self.csm.air.dbId,
            self.accountId,
            self.csm.air.dclassesByName['AccountUD'],
            fields)

        # We're done.
        self.csm.air.writeServerEvent('accountLogin', self.target, self.accountId, self.databaseId)
        self.csm.sendUpdateToChannel(self.target, 'acceptLogin', [])
        self.demand('Off')

class CreateAvatarFSM(OperationFSM):
    notify = directNotify.newCategory('CreateAvatarFSM')

    def enterStart(self, dna, name, index, tf, hood, trackChoice):
        # Basic sanity-checking:
        if index >= 6:
            self.demand('Kill', 'Invalid index specified!')
            return

        if not ToonDNA().isValidNetString(dna):
            self.demand('Kill', 'Invalid DNA specified!')
            return

        self.index = index
        self.dna = dna
        self.name = name
        self.tf = tf
        self.hood = hood
        self.trackChoice = trackChoice
        self.__pendingName = ""
        
        # Okay, we're good to go, let's query their account.
        self.demand('RetrieveAccount')

    def enterRetrieveAccount(self):
        # self.target is the accountId, so:
        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.target,
                                             self.__handleRetrieve)

    def __handleRetrieve(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['AccountUD']:
            self.demand('Kill', 'Your account object was not found in the database!')
            return

        self.account = fields

        self.avList = self.account['ACCOUNT_AV_SET']
        # Sanitize; just in case avList is too long/short:
        self.avList = self.avList[:6]
        self.avList += [0] * (6-len(self.avList))

        # Make sure the index is open:
        if self.avList[self.index]:
            self.demand('Kill', 'This avatar slot is already taken by another avatar!')
            return

        # Okay, there's space, let's create the avatar!
        self.demand('CreateAvatar')

    def enterCreateAvatar(self):
        dna = ToonDNA()
        dna.makeFromNetString(self.dna)
            
        dg = PyDatagram(self.name)
        dgi = PyDatagramIterator(dg)
        isPattern, name = isNamePattern(dgi, self.csm.namePattern, dna.gender)
        
        if not name:
            self.demand('Kill', 'There\'s an issue with your name request!')
            return
        
        if not isPattern:
            self.__pendingName = name
            colorstring = TTLocalizer.NumToColor[dna.headColor]
            animaltype = TTLocalizer.AnimalToSpecies[dna.getAnimal()]
            name = colorstring + ' ' + animaltype

        toonFields = {
            'setName': (name,),
            'WishNameState': ('PENDING' if not isPattern else '',),
            'WishName': (self.__pendingName,),
            'setDNAString': (self.dna,),
            'setDISLid': (self.target,)
        }
        
        if not self.tf and not self.hood:
            toonFields['setTutorialAck'] = (1,)
            toonFields['setQuests'] = ([163, 1000, 1000, 100, 3],)
            
        if self.hood:
            hqZones = []
            
            if self.hood == 1: # dd
                if not -1 in self.trackChoice:
                    self.demand('Kill', 'Invalid track choice for DD!')
                    return
                    
                jarsize = 50
                gaglimit = 25
                hoodId = 1000
                prevZones = [2000]
                questlimit = 2
                tier = 4
                hp = 25
                expm = 1500
                
            elif self.hood == 2: # dg
                if -1 in self.trackChoice:
                    self.demand('Kill', 'Invalid track choice for DG!')
                    return
                    
                jarsize = 60
                gaglimit = 30
                hoodId = 5000
                prevZones = [1000, 2000]
                questlimit = 2
                tier = 7
                hp = 34
                expm = 2300
                
            elif self.hood == 3 and config.GetBool('csp-want-mm', False): # mm (MIGHT BE DISABLED)
                if -1 in self.trackChoice:
                    self.demand('Kill', 'Invalid track choice for MM!')
                    return
                    
                jarsize = 80
                gaglimit = 35
                hoodId = 4000
                prevZones = [1000, 2000, 5000]
                questlimit = 3
                tier = 8
                hp = 43
                expm = 4000
                hqZones = [11000]
                toonFields['setCogParts'] = ((0, 0, 0, 1),)
                
            else:
                self.demand('Kill', 'Invalid hood!')
                return
                
            ta = [0, 0, 0, 0, 1, 1, 0]
            for t in self.trackChoice:
                if t != -1:
                    ta[t] = 1
                
            toonFields['setMaxMoney'] = (jarsize,)
            toonFields['setMaxCarry'] = (gaglimit,)
            toonFields['setTrackAccess'] = (ta,)
            toonFields['setDefaultZone'] = (hoodId,)
            toonFields['setHoodsVisited'] = (prevZones + hqZones + [hoodId],)
            toonFields['setZonesVisited'] = (prevZones + hqZones + [hoodId],)
            toonFields['setTeleportAccess'] = (prevZones,)
            toonFields['setQuestCarryLimit'] = (questlimit,)
            toonFields['setRewardHistory'] = (tier, [])
            toonFields['setHp'] = (hp,)
            toonFields['setMaxHp'] = (hp,)
            toonFields['setTutorialAck'] = (1,)
            
            e = Experience()
            e.makeExpRegular(expm)
            
            for i, t in enumerate(ta):
                if not t:
                    e.experience[i] = 0
                    
            toonFields['setExperience'] = (e.makeNetString(),)

        self.csm.air.dbInterface.createObject(
            self.csm.air.dbId,
            self.csm.air.dclassesByName['DistributedToonUD'],
            toonFields,
            self.__handleCreate)

    def __handleCreate(self, avId):
        if not avId:
            self.demand('Kill', 'Database failed to create the new avatar object!')
            return

        self.avId = avId
        if self.__pendingName:
            self.csm.accountDB.handlePostNameRequest(self.avId, self.__pendingName)
        
        self.__pendingName = ""

        self.demand('StoreAvatar')

    def enterStoreAvatar(self):
        # Associate the avatar with the account...
        self.avList[self.index] = self.avId

        self.csm.air.dbInterface.updateObject(
            self.csm.air.dbId,
            self.target, # i.e. the account ID
            self.csm.air.dclassesByName['AccountUD'],
            {'ACCOUNT_AV_SET': self.avList},
            {'ACCOUNT_AV_SET': self.account['ACCOUNT_AV_SET']},
            self.__handleStoreAvatar)

    def __handleStoreAvatar(self, fields):
        if fields:
            # TODO: delete self.avId
            self.demand('Kill', 'Database failed to associate the new avatar to your account!')
            return

        # Otherwise, we're done!
        self.csm.air.writeServerEvent('avatarCreated', self.avId, self.target, self.dna.encode('hex'), self.index)
        self.csm.sendUpdateToAccountId(self.target, 'createAvatarResp', [self.avId])
        self.demand('Off')

class AvatarOperationFSM(OperationFSM):
    POST_ACCOUNT_STATE = 'Off'

    def enterRetrieveAccount(self):
        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.target,
                                             self.__handleRetrieve)

    def __handleRetrieve(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['AccountUD']:
            self.demand('Kill', 'Your account object was not found in the database!')
            return

        self.account = fields
        self.avList = self.account['ACCOUNT_AV_SET']
        # Sanitize; just in case avList is too long/short:
        self.avList = self.avList[:6]
        self.avList += [0] * (6-len(self.avList))

        self.demand(self.POST_ACCOUNT_STATE)

class GetAvatarsFSM(AvatarOperationFSM):
    notify = directNotify.newCategory('GetAvatarsFSM')
    POST_ACCOUNT_STATE = 'QueryAvatars'

    def enterStart(self):
        self.demand('RetrieveAccount')

    def enterQueryAvatars(self):
        self.pendingAvatars = set()
        self.avatarFields = {}
        for avId in self.avList:
            if avId:
                self.pendingAvatars.add(avId)

                def response(dclass, fields, avId=avId):
                    if self.state != 'QueryAvatars': return
                    if dclass != self.csm.air.dclassesByName['DistributedToonUD']:
                        self.demand('Kill', "One of the account's avatars is invalid!")
                        return
                    if not fields.has_key('setDISLid'):
                        self.csm.air.dbInterface.updateObject(
                            self.csm.air.dbId,
                            avId,
                            self.csm.air.dclassesByName['DistributedToonUD'],
                            {'setDISLid' : [self.target]}
                        )
                    self.avatarFields[avId] = fields
                    self.pendingAvatars.remove(avId)
                    if not self.pendingAvatars:
                        self.demand('UpdateAvatarsNameState')

                self.csm.air.dbInterface.queryObject(self.csm.air.dbId, avId,
                                                     response)

        if not self.pendingAvatars:
            self.demand('SendAvatars')
            
    def enterUpdateAvatarsNameState(self):
        self.pendingAvatars = set()
        
        for avId, fields in self.avatarFields.items():
            wns = fields.get('WishNameState', [''])[0]
            if wns == "PENDING":
                def response(state, avId=avId):                        
                    if state == NAME_PENDING:
                        wns = "PENDING"
                        
                    elif state == NAME_REJECTED:
                        wns = "REJECTED"
                        
                    elif state == NAME_APPROVED:
                        wns = "APPROVED"
                        
                    self.avatarFields[avId]['WishNameState'] = (wns,)
                    
                    self.csm.air.dbInterface.updateObject(
                            self.csm.air.dbId,
                            avId,
                            self.csm.air.dclassesByName['DistributedToonUD'],
                            self.avatarFields[avId]
                        )
                        
                    self.pendingAvatars.remove(avId)
                    if not self.pendingAvatars:
                        taskMgr.doMethodLater(0, GetAvatarsFSM.demand, 'demand-SendAvatars', extraArgs=[self, 'SendAvatars'])
                        
                self.pendingAvatars.add(avId)
                self.csm.accountDB.getNameStatus(avId, response)
                        
        if not self.pendingAvatars:
            taskMgr.doMethodLater(0, GetAvatarsFSM.demand, 'demand-SendAvatars', extraArgs=[self, 'SendAvatars'])
                        
    def enterSendAvatars(self):
        potentialAvs = []

        for avId, fields in self.avatarFields.items():
            index = self.avList.index(avId)
            wns = fields.get('WishNameState', [''])[0]
            name = fields['setName'][0]
            if wns == 'OPEN':
                nameState = 1
            elif wns == 'PENDING':
                nameState = 2
            elif wns == 'APPROVED':
                nameState = 3
                name = fields['WishName'][0]
            elif wns == 'REJECTED':
                nameState = 4
            elif wns == '':
                nameState = 0
            else:
                self.csm.notify.warning('Avatar %d is in unknown name state %s.' % (avId, wns))
                nameState = 0

            potentialAvs.append([avId, name, fields['setDNAString'][0],
                                 index, nameState, fields['setHp'][0],
                                 fields['setMaxHp'][0], fields['setLastHood'][0]])

        self.csm.sendUpdateToAccountId(self.target, 'setAvatars', [potentialAvs])
        self.demand('Off')
        
    def enterOff(self):
        try:
            if self.TARGET_CONNECTION:
                del self.csm.connection2fsm[self.target]
            else:
                del self.csm.account2fsm[self.target]
                
        except KeyError:
            pass

class DeleteAvatarFSM(GetAvatarsFSM):
    notify = directNotify.newCategory('DeleteAvatarFSM')
    POST_ACCOUNT_STATE = 'ProcessDelete'

    def enterStart(self, avId):
        self.avId = avId
        GetAvatarsFSM.enterStart(self)

    def enterProcessDelete(self):
        if self.avId not in self.avList:
            self.demand('Kill', 'Tried to delete an avatar not in the account!')
            return

        index = self.avList.index(self.avId)
        self.avList[index] = 0

        avsDeleted = list(self.account.get('ACCOUNT_AV_SET_DEL', []))
        avsDeleted.append([self.avId, int(time.time())])
        
        estateId = self.account.get('ESTATE_ID', 0)
        
        if estateId != 0:
            # This assumes that the house already exists, but it shouldn't
            # be a problem if it doesn't.
            self.csm.air.dbInterface.updateObject(
                self.csm.air.dbId,
                estateId,
                self.csm.air.dclassesByName['DistributedEstateAI'],
                { 'setSlot%dToonId' % index : [0] }
            )

        self.csm.air.dbInterface.updateObject(
            self.csm.air.dbId,
            self.target, # i.e. the account ID
            self.csm.air.dclassesByName['AccountUD'],
            {'ACCOUNT_AV_SET': self.avList,
             'ACCOUNT_AV_SET_DEL': avsDeleted},
            {'ACCOUNT_AV_SET': self.account['ACCOUNT_AV_SET'],
             'ACCOUNT_AV_SET_DEL': self.account['ACCOUNT_AV_SET_DEL']},
            self.__handleDelete)      
            
    def __handleDelete(self, fields):
        if fields:
            self.demand('Kill', 'Database failed to mark the avatar deleted!')
            return
        
        self.csm.air.friendsManager.clearList(self.avId) #RIP friends list
        self.csm.air.writeServerEvent('avatarDeleted', self.avId, self.target)
        self.demand('QueryAvatars')

class UpdateNameFSM(AvatarOperationFSM):
    notify = directNotify.newCategory('SetNameTypedFSM')
    POST_ACCOUNT_STATE = 'RetrieveAvatar'

    def enterStart(self, avId, name):
        self.avId = avId
        self.name = name

        if self.avId:
            self.demand('RetrieveAccount')
            return

        else:
            # Hmm, self.avId was 0. Shouldn't happen.
            self.demand('Kill', 'Invalid avId')

    def enterRetrieveAvatar(self):
        if self.avId and self.avId not in self.avList:
            self.demand('Kill', 'Tried to name an avatar not in the account!')
            return

        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.avId,
                                             self.__handleAvatar)

    def __handleAvatar(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['DistributedToonUD']:
            self.demand('Kill', "One of the account's avatars is invalid!")
            return

        if fields['WishNameState'][0] != 'OPEN':
            self.demand('Kill', 'Avatar is not in a namable state!')
            return

        self.dna = ToonDNA(fields['setDNAString'][0])
        self.demand('JudgeName')

    def enterJudgeName(self):
        dg = PyDatagram(self.name)
        dgi = PyDatagramIterator(dg)
        isPattern, name = isNamePattern(dgi, self.csm.namePattern, self.dna.gender)
        
        if not name:
            self.demand('Kill', 'There\'s an issue with your name request!')
            return
        
        toonFields = {'WishNameState': ('PENDING',), 'WishName': (name,)}
        
        if isPattern:
            toonFields['WishNameState'] = ('',)
            toonFields['WishName'] = ('',)
            toonFields['setName'] = (name,)

        if self.avId:
            self.csm.air.dbInterface.updateObject(
                self.csm.air.dbId,
                self.avId,
                self.csm.air.dclassesByName['DistributedToonUD'],
                toonFields)

            self.csm.air.writeServerEvent('avatarWishname', self.avId, name)
            self.csm.accountDB.handlePostNameRequest(self.avId, name)

        self.csm.sendUpdateToAccountId(self.target, 'updateNameResp', [])
        self.demand('Off')

class AcknowledgeNameFSM(AvatarOperationFSM):
    notify = directNotify.newCategory('AcknowledgeNameFSM')
    POST_ACCOUNT_STATE = 'GetTargetAvatar'

    def enterStart(self, avId):
        self.avId = avId
        self.demand('RetrieveAccount')

    def enterGetTargetAvatar(self):
        # Make sure the target avatar is part of the account:
        if self.avId not in self.avList:
            self.demand('Kill', 'Tried to acknowledge name on an avatar not in the account!')
            return

        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.avId,
                                             self.__handleAvatar)

    def __handleAvatar(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['DistributedToonUD']:
            self.demand('Kill', "One of the account's avatars is invalid!")
            return

        # Process the WishNameState change.
        wns = fields['WishNameState'][0]
        wn = fields['WishName'][0]
        name = fields['setName'][0]

        if wns == 'APPROVED':
            wns = ''
            name = wn
            wn = ''
        elif wns == 'REJECTED':
            wns = 'OPEN'
            wn = ''
        else:
            self.demand('Kill', "Tried to acknowledge name on an avatar in %s state!" % wns)
            return

        # Push the change back through:
        self.csm.air.dbInterface.updateObject(
            self.csm.air.dbId,
            self.avId,
            self.csm.air.dclassesByName['DistributedToonUD'],
            {'WishNameState': (wns,),
             'WishName': (wn,),
             'setName': (name,)},
            {'WishNameState': fields['WishNameState'],
             'WishName': fields['WishName'],
             'setName': fields['setName']})

        self.csm.sendUpdateToAccountId(self.target, 'acknowledgeAvatarNameResp', [])
        self.demand('Off')

class LoadAvatarFSM(AvatarOperationFSM):
    notify = directNotify.newCategory('LoadAvatarFSM')
    POST_ACCOUNT_STATE = 'GetTargetAvatar'

    def enterStart(self, avId):
        self.avId = avId
        self.demand('RetrieveAccount')

    def enterGetTargetAvatar(self):
        # Make sure the target avatar is part of the account:
        if self.avId not in self.avList:
            self.demand('Kill', 'Tried to play an avatar not in the account!')
            return

        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.avId,
                                             self.__handleAvatar)

    def __handleAvatar(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['DistributedToonUD']:
            self.demand('Kill', "One of the account's avatars is invalid!")
            return

        self.avatar = fields
        self.demand('SetAvatar')

    def enterSetAvatar(self):
        channel = self.csm.GetAccountConnectionChannel(self.target)

        # First, give them a POSTREMOVE to unload the avatar, just in case they
        # disconnect while we're working.
        dgcleanup = PyDatagram()
        dgcleanup.addServerHeader(self.avId, channel, STATESERVER_OBJECT_DELETE_RAM)
        dgcleanup.addUint32(self.avId)
        dg = PyDatagram()
        dg.addServerHeader(channel, self.csm.air.ourChannel, CLIENTAGENT_ADD_POST_REMOVE)
        dg.addString(dgcleanup.getMessage())
        self.csm.air.send(dg)

        # Activate the avatar on the DBSS:
        self.csm.air.sendActivate(self.avId, 0, 0,
                                  self.csm.air.dclassesByName['DistributedToonUD'],
                                  {'setAdminAccess': [self.account.get('ADMIN_ACCESS', 0)]})

        # Next, add them to the avatar channel:
        dg = PyDatagram()
        dg.addServerHeader(channel, self.csm.air.ourChannel, CLIENTAGENT_OPEN_CHANNEL)
        dg.addChannel(self.csm.GetPuppetConnectionChannel(self.avId))
        self.csm.air.send(dg)

        # Now set their sender channel to represent their account affiliation:
        dg = PyDatagram()
        dg.addServerHeader(channel, self.csm.air.ourChannel, CLIENTAGENT_SET_CLIENT_ID)
        dg.addChannel(self.target<<32 | self.avId) # accountId in high 32 bits, avatar in low
        self.csm.air.send(dg)

        # Finally, grant ownership and shut down.
        dg = PyDatagram()
        dg.addServerHeader(self.avId, self.csm.air.ourChannel, STATESERVER_OBJECT_SET_OWNER)
        dg.addChannel(self.target<<32 | self.avId) # accountId in high 32 bits, avatar in low
        self.csm.air.send(dg)
        
        # Tell TTFriendsManager somebody is logging in:
        fields = self.avatar
        fields.update({'setAdminAccess': [self.account.get('ADMIN_ACCESS', 0)]})
        self.csm.air.friendsManager.toonOnline(self.avId, fields)

        # Tell the GlobalPartyManager as well
        self.csm.air.globalPartyMgr.avatarJoined(self.avId)

        self.csm.air.writeServerEvent('avatarChosen', self.avId, self.target)
        self.demand('Off')

class UnloadAvatarFSM(OperationFSM):
    notify = directNotify.newCategory('UnloadAvatarFSM')

    def enterStart(self, avId):
        self.avId = avId

        # We don't even need to query the account, we know the avatar is being played!
        self.demand('UnloadAvatar')

    def enterUnloadAvatar(self):
        channel = self.csm.GetAccountConnectionChannel(self.target)
        
        # Tell FriendsManager somebody is logging off:
        self.csm.air.friendsManager.toonOffline(self.avId)

        # Clear off POSTREMOVE:
        dg = PyDatagram()
        dg.addServerHeader(channel, self.csm.air.ourChannel, CLIENTAGENT_CLEAR_POST_REMOVES)
        self.csm.air.send(dg)

        # Remove avatar channel:
        dg = PyDatagram()
        dg.addServerHeader(channel, self.csm.air.ourChannel, CLIENTAGENT_CLOSE_CHANNEL)
        dg.addChannel(self.csm.GetPuppetConnectionChannel(self.avId))
        self.csm.air.send(dg)

        # Reset sender channel:
        dg = PyDatagram()
        dg.addServerHeader(channel, self.csm.air.ourChannel, CLIENTAGENT_SET_CLIENT_ID)
        dg.addChannel(self.target<<32) # accountId in high 32 bits, no avatar in low
        self.csm.air.send(dg)

        # Unload avatar object:
        dg = PyDatagram()
        dg.addServerHeader(self.avId, channel, STATESERVER_OBJECT_DELETE_RAM)
        dg.addUint32(self.avId)
        self.csm.air.send(dg)

        # Done!
        self.csm.air.writeServerEvent('avatarUnload', self.avId)
        self.demand('Off')
        
class FetchUsernameFSM(OperationFSM):
    notify = directNotify.newCategory('FetchUsernameFSM')

    def enterStart(self, callback):
        self.callback = callback
        self.demand('RetrieveAccount')

    def enterRetrieveAccount(self):
        # self.target is the accountId, so:
        self.csm.air.dbInterface.queryObject(self.csm.air.dbId, self.target,
                                             self.__handleRetrieve)

    def __handleRetrieve(self, dclass, fields):
        if dclass != self.csm.air.dclassesByName['AccountUD']:
            self.demand('Kill', 'Your account object was not found in the database!')
            return

        self.callback(fields['ACCOUNT_ID'])
        self.demand('Off')
        
    def enterOff(self):
        pass

class ClientServicesManagerUD(DistributedObjectGlobalUD):
    notify = directNotify.newCategory('ClientServicesManagerUD')

    def announceGenerate(self):
        DistributedObjectGlobalUD.announceGenerate(self)

        self.connection2fsm = {}
        self.account2fsm = {}

        self.nameGenerator = NameGenerator()
        self.namePattern = NamePattern()

        accType = config.GetString('account-db-type', 'local')
        if accType == 'local':
            self.accountDB = LocalAccountDB(self)
            
        elif accType == 'server':
            self.accountDB = ServerAccountDB(self)
            
        elif accType == 'trapdoor':
            self.accountDB = TrapDoorAccountDB(self)
            self.notify.warning('Trapdoor activated!')
            
        else:
            self.notify.warning('Invalid accType %s, UD will reject all logins!' % accType)
            self.accountDB = None
            
    def killConnection(self, connId, reason):
        dg = PyDatagram()
        dg.addServerHeader(connId, self.air.ourChannel, CLIENTAGENT_EJECT)
        dg.addUint16(122)
        dg.addString(reason)
        self.air.send(dg)

    def killConnectionFSM(self, connId):
        fsm = self.connection2fsm.get(connId)
        if not fsm:
            self.notify.warning('Tried to kill connection %d for duplicate FSM, but none exists!' % connId)
            return
        self.killConnection(connId, 'An operation is already underway: ' + fsm.name)

    def killAccount(self, accountId, reason):
        self.killConnection(self.GetAccountConnectionChannel(accountId), reason)

    def killAccountFSM(self, accountId):
        fsm = self.account2fsm.get(accountId)
        if not fsm:
            self.notify.warning('Tried to kill account %d for duplicate FSM, but none exists!' % accountId)
            return
        self.killAccount(accountId, 'An operation is already underway: ' + fsm.name)

    def runAccountFSM(self, fsmtype, *args):
        sender = self.air.getAccountIdFromSender()

        if not sender:
            self.killAccount(sender, 'Client is not logged in.')

        if sender in self.account2fsm:
            self.killAccountFSM(sender)
            return

        self.account2fsm[sender] = fsmtype(self, sender)
        self.account2fsm[sender].request('Start', *args)

    def login(self, cookie, hash):
        self.notify.debug('Received login cookie %r from %d' % (cookie, self.air.getMsgSender()))

        sender = self.air.getMsgSender()

        if sender >> 32:
            # Already logged!
            # TO DO: allow logout
            self.killConnection(sender, 'Client is already logged in.')
            return
            
        if not self.accountDB:
            self.killConnection(sender, 'The UD cannot handle logins at the moment.')
            return

        if sender in self.connection2fsm:
            self.killConnectionFSM(sender)
            return
            
        secret = "dev" if self.accountDB.__class__ == LocalAccountDB else self.air.getApiKey()
        h = hashlib.sha512()
        h.update(cookie + secret)
        dg = h.digest()
        
        if len(dg) != len(hash):
            self.killConnection(sender, 'Bad request.')
            return
        
        result = 0
        for x, y in zip(hash, dg):
            result |= ord(x) ^ ord(y)
        
        if result:
            self.killConnection(sender, 'Bad request.')
            return

        self.connection2fsm[sender] = LoginAccountFSM(self, sender)
        self.connection2fsm[sender].request('Start', cookie)

    def requestAvatars(self):
        self.notify.debug('Received avatar list request from %d' % (self.air.getMsgSender()))
        self.runAccountFSM(GetAvatarsFSM)

    def createAvatar(self, dna, name, index, tf, hood, trackChoice):
        self.runAccountFSM(CreateAvatarFSM, dna, name, index, tf, hood, trackChoice)

    def deleteAvatar(self, avId):
        self.runAccountFSM(DeleteAvatarFSM, avId)

    def updateName(self, avId, name):
        self.runAccountFSM(UpdateNameFSM, avId, name)
        
    def acknowledgeAvatarName(self, avId):
        self.runAccountFSM(AcknowledgeNameFSM, avId)

    def chooseAvatar(self, avId):
        currentAvId = self.air.getAvatarIdFromSender()
        accountId = self.air.getAccountIdFromSender()
        
        if currentAvId and avId:
            self.killAccount(accountId, 'A Toon is already chosen!')
            return
            
        elif not currentAvId and not avId:
            return

        if avId:
            self.runAccountFSM(LoadAvatarFSM, avId)
            
        else:
            self.runAccountFSM(UnloadAvatarFSM, currentAvId)

    def getUsername(self, accountId, callback):
        FetchUsernameFSM(self, accountId).demand('Start', callback)
        