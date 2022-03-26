all:

PREFIX = ${HOME}/.local
BINDIR = ${PREFIX}/bin
SOUNDSDIR = ${PREFIX}/share/sounds

install:
	install -m 755 -d ${BINDIR}
	install -m 755 watchRain.py ${BINDIR}
	
	install -m 755 -d ${SOUNDSDIR}
	install -m 644 observation-10.wav ${SOUNDSDIR}
	install -m 644 observation-20.wav ${SOUNDSDIR}
	install -m 644 observation-30.wav ${SOUNDSDIR}
	install -m 644 observation-40.wav ${SOUNDSDIR}
	install -m 644 observation-50.wav ${SOUNDSDIR}
	install -m 644 observation-60.wav ${SOUNDSDIR}
	install -m 644 forecast-10.wav    ${SOUNDSDIR}
	install -m 644 forecast-20.wav    ${SOUNDSDIR}
	install -m 644 forecast-30.wav    ${SOUNDSDIR}
	install -m 644 forecast-40.wav    ${SOUNDSDIR}
	install -m 644 forecast-50.wav    ${SOUNDSDIR}
	install -m 644 forecast-60.wav    ${SOUNDSDIR}
