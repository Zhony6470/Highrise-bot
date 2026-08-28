#!/usr/bin/env bash
set -e

apt-get update
apt-get install -y icecast2 ffmpeg

cat > /etc/icecast2/icecast.xml <<'EOF'
<icecast>
  <hostname>localhost</hostname>

  <listen-socket>
    <port>8000</port>
  </listen-socket>

  <paths>
    <basedir>/usr/share/icecast2</basedir>
    <webroot>/usr/share/icecast2/web</webroot>
    <adminroot>/usr/share/icecast2/admin</adminroot>
    <logdir>/var/log/icecast2</logdir>
    <pidfile>/var/run/icecast2/icecast.pid</pidfile>
  </paths>

  <logging>
    <accesslog>access.log</accesslog>
    <errorlog>error.log</errorlog>
    <loglevel>3</loglevel>
  </logging>

  <security>
    <chroot>0</chroot>
    <changeowner>
      <user>icecast</user>
      <group>icecast</group>
    </changeowner>
  </security>

  <mount>
    <mount-name>/stream</mount-name>
    <username>source</username>
    <password>password</password>
    <max-listeners>20</max-listeners>
  </mount>
</icecast>
EOF

icecast2 -b -c /etc/icecast2/icecast.xml
sleep 3

if [ -f /tmp/input.mp3 ]; then
  echo "Usando /tmp/input.mp3"
else
  ffmpeg -f lavfi -i sine=frequency=440:duration=10 -q:a 9 -ar 44100 /tmp/input.mp3
fi

ffmpeg -re -i /tmp/input.mp3 -c:a libmp3lame -b:a 128k -f mp3 \
  icecast://source:password@127.0.0.1:8000/stream &

python main.py
