set("log.stdout", true)

def required(name)
  value = getenv(name)
  if value == "" then
    fail("Falta la variable de entorno " ^ name)
  end
  value
end

icecast_host = required("ICECAST_HOST")
icecast_port = int_of_string(required("ICECAST_PORT"))
icecast_password = required("ICECAST_PASSWORD")
icecast_mount = getenv("ICECAST_MOUNT")
if icecast_mount == "" then
  icecast_mount = "stream"
end
source = input.http("http://127.0.0.1:8090/stream")

output.icecast(
  %mp3(bitrate=128),
  host=icecast_host,
  port=icecast_port,
  password=icecast_password,
  mount=icecast_mount,
  source
)