# Continuous production radio. AutoDJ controls the queues; Liquidsoap owns the audio clock.
settings.log.stdout := true
settings.log.level := 3

settings.server.telnet := true
settings.server.telnet.bind_addr := "0.0.0.0"
settings.server.telnet.port := 1234
settings.server.telnet.revdns := false

settings.frame.audio.samplerate := 44100
settings.frame.audio.channels := 2

icecast_host = environment.get(default="icecast", "ICECAST_HOST")
icecast_port = int_of_string(environment.get(default="8000", "ICECAST_PORT"))
icecast_password = environment.get(default="", "ICECAST_PASSWORD")
icecast_mount = environment.get(default="stream", "ICECAST_MOUNT")

requests = request.queue(id="requests", interactive=true, prefetch=2)

defaults = request.queue(id="defaults", interactive=true, prefetch=2)

background = crossfade(
  duration=2.,
  fade_in=1.,
  fade_out=1.,
  smart=true,
  defaults
)

def to_requests(old, new) =
  # A request interrupts the current default. Skip the old background source
  # so that, after the request finishes, fallback starts a fresh default
  # instead of resuming the interrupted default fragment.
  source.skip(old)
  new
end

def to_background(old, new) =
  new
end

radio = fallback(
  id="radio",
  track_sensitive=false,
  transitions=[to_requests, to_background],
  [requests, background]
)

radio = mksafe(radio)

output.icecast(
  %mp3(bitrate=128),
  host=icecast_host,
  port=icecast_port,
  password=icecast_password,
  mount=icecast_mount,
  name="Highrise Radio",
  public=false,
  send_icy_metadata=true,
  radio
)
