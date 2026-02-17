The FNIRSI IR-40 is a cheap chinese bluetooth laser. It is accurate and small and portable. It comes with an APP that works well on Android. Others have written a python script that reads the laser and pastes the value, very useful.
Sadly this does not work on Linux due to issues with bluez. But after much testing I found a way to make it work using dbus. I present to you a python script that works. You need to install the dependancies, pynput and dbus-next.
This works for me on Linux Mint.
