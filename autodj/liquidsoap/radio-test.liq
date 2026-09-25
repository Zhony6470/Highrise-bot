# First-stage Liquidsoap test.
# This service intentionally uses a separate Icecast mount so the current
# /stream production path remains untouched during validation.

settings.log.stdout := true
settings.log.level := 3

icecast_host = environment.get(default="icecast", "ICECAST_HOST")
icecast_port = int_of_string(environment.get(default="8000", "ICECAST_PORT"))
icecast_password = environment.get(default="", "ICECAST_PASSWORD")
icecast_mount = environment.get(default="liquidsoap-test", "ICECAST_MOUNT")

music = mksafe(
  playlist(
    id="test_playlist",
    reload=30,
    mode="randomize",
    "/data/default_music"
  )
)

output.icecast(
  %mp3(bitrate=128),
  host=icecast_host,
  port=icecast_port,
  password=icecast_password,
  mount=icecast_mount,
  name="Highrise Liquidsoap Test",
  public=false,
  send_icy_metadata=true,
  music
)
