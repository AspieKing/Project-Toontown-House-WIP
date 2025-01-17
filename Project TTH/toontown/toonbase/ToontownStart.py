from pandac.PandaModules import *
import __builtin__

if __debug__:
    loadPrcFile('prc/dev.prc')
    loadPrcFile('prc/server.prc')
    
    # let's check if they edited the prc server stuff
    config = getConfigExpress()
    defaultServer = '127.0.0.1'
    if config.GetString('game-server', defaultServer) != defaultServer:
        print 'YOU EDITED THE PRC SERVER!!!'
        print 'DO NOT DO THIS!!'
        print 'USE "-s IP" INSTEAD!'
        
    defaultToken = 'dev'
    if config.GetString('fake-playtoken', defaultToken) != defaultToken:
        print 'YOU EDITED THE PRC TOKEN!!!'
        print 'DO NOT DO THIS!!'
        print 'USE "-t TOKEN" INSTEAD!'

class game:
    name = 'toontown'
    process = 'client'

__builtin__.game = game()

import time, os, sys, random

customServer = False
if '-s' in sys.argv:
    server = sys.argv[sys.argv.index('-s') + 1]
    
    if __debug__:
        if server == "lc":
            server = "173.237.116.184"

    customServer = True
    loadPrcFileData('', 'game-server ' + server)

if '-t' in sys.argv:
	token = sys.argv[sys.argv.index('-t') + 1]
	loadPrcFileData('', 'fake-playtoken ' + token)

else:
    if customServer:
        print 'You must use a token (-t) with -s!'
        exit()
    
if '-v' in sys.argv:
    ver = sys.argv[sys.argv.index('-v') + 1]
    loadPrcFileData('', 'server-version ' + ver)
    
if '-l' in sys.argv:
    langMap = {'pt': 'portuguese', 'en': 'english', 'fr': 'french'}
    lang = sys.argv[sys.argv.index('-l') + 1]
    
    if lang == "en":
        print 'WARNING: default language is already English!'
       
    elif lang not in langMap:
        print 'ERROR: invalid lang', lang
        print 'THE LANGUAGES ARE:'
        for l in langMap:
            print '\t', l
          
        print

    loadPrcFileData('', 'language ' + langMap[lang])

from toontown.launcher.TTLauncher import TTLauncher
__builtin__.launcher = TTLauncher()

print 'ToontownStart: Starting the game.'
    
tempLoader = Loader()
backgroundNode = tempLoader.loadSync(Filename('phase_3/models/gui/loading-background'))

from direct.gui import DirectGuiGlobals
from direct.gui.DirectGui import *
import toontown.toonbase.ToontownGlobals
def ToontownGlobals():
 DirectGuiGlobals.setDefaultFontFunc(ToontownGlobals.getInterfaceFont)
 launcher.setPandaErrorCode(7)

# base
import ToonBase
ToonBase.ToonBase()
def ToonBase():
 base.loadSettings()

 if base.win == None:
    print 'Unable to open window; aborting.'
    sys.exit()
def TTLauncher():
 launcher.setPandaErrorCode(0)
 launcher.setPandaWindowOpen()
 ConfigVariableDouble('decompressor-step-time').setValue(0.01)
 ConfigVariableDouble('extractor-step-time').setValue(0.01)
 backgroundNodePath = aspect2d.attachNewNode(backgroundNode, 0)
 backgroundNodePath.setPos(0.0, 0.0, 0.0)
 backgroundNodePath.setScale(render2d, VBase3(1))
 backgroundNodePath.find('**/fg').hide()
 logo = OnscreenImage(
 image='phase_3/maps/toontown-logo-new.png',
 scale=(1 / (4.0/3.0), 1, 1 / (4.0/3.0)),
 pos=backgroundNodePath.find('**/fg').getPos())
 logo.setTransparency(TransparencyAttrib.MAlpha)
 logo.setBin('fixed', 20)
 logo.reparentTo(backgroundNodePath)
# backgroundNodePath.find('**/fg').setBin('fixed', 20)
# backgroundNodePath.find('**/fg').setScale(1 / (4.0/3.0), 1, 16.0 / 9.0)
 backgroundNodePath.find('**/bg').setBin('fixed', 10)
 base.graphicsEngine.renderFrame()
 DirectGuiGlobals.setDefaultRolloverSound(base.loadSfx('phase_3/audio/sfx/GUI_rollover.ogg'))
 DirectGuiGlobals.setDefaultClickSound(base.loadSfx('phase_3/audio/sfx/GUI_create_toon_fwd.ogg'))
 DirectGuiGlobals.setDefaultDialogGeom(loader.loadModel('phase_3/models/gui/dialog_box_gui'))
import TTLocalizer
from otp.otpbase import OTPGlobals
OTPGlobals.setDefaultProductPrefix(TTLocalizer.ProductPrefix)
# loading music
music = None
def ToonBase():
    if base.musicManagerIsValid:
     music = base.musicManager.getSound('phase_3/audio/bgm/tt_theme.ogg')
    if music:
     music.setLoop(1)
     music.setVolume(0.9)
     music.play()

# loader
import ToontownLoader
from direct.gui.DirectGui import *
def ToonBase():
 serverVersion = base.config.GetString('server-version', 'no_version_set')
 version = OnscreenText(serverVersion, pos=(-1.3, -0.975), scale=0.06, fg=Vec4(0, 0, 0, 1), align=TextNode.ALeft)
 loader.beginBulkLoad('init', TTLocalizer.LoaderLabel, 138, 0, TTLocalizer.TIP_GENERAL, 1)
from ToonBaseGlobal import *
from otp.otpbase.MessengerGlobal import *

# cr
from toontown.distributed import ToontownClientRepository
cr = ToontownClientRepository.ToontownClientRepository(serverVersion, launcher)
cr.setDeferInterval(1)
cr.music = music
del music
base.initNametagGlobals()
base.cr = cr
loader.endBulkLoad('init')

# friend mgr
from otp.friends import FriendManager
from otp.distributed.OtpDoGlobals import *
cr.generateGlobalObject(OTP_DO_ID_FRIEND_MANAGER, 'FriendManager')

# start
base.startShow(cr)

# cleanup
backgroundNodePath.reparentTo(hidden)
backgroundNodePath.removeNode()
del backgroundNodePath
del backgroundNode
del tempLoader
del logo
version.cleanup()
del version

try:
    run()
    
except SystemExit:
    try:
        __nirai__
    
    except:
        raise SystemExit
    
except KeyboardInterrupt:
    raise
    
except:
    try:
        base.cr.timeManager.setDisconnectReason(3)
    
    except:
        pass
        
    raise
    