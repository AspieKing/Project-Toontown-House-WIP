"""instantiate global Messenger object"""

__all__ = ['messenger']

import otp.otpbase.Messenger
def Messenger():
    messenger = Messenger.Messenger()
