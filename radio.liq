set("log.stdout", true)

def required(name)
  value = getenv(name)
  if value == "" then
    fail("Falta la variable de entorno " ^ name)
  end
  value
end

shoutcast_host = required("SHOUTCAST_HOST")
shoutcast_port = int_of_string(required("SHOUTCAST_PORT"))
shoutcast_password = required("SHOUTCAST_PASSWORD")
source = input.http("http://127.0.0.1:8090/stream")

output.icecast(
  %mp3(bitrate=128),
  protocol="icy",
  host=shoutcast_host,
  port=shoutcast_port,
  password=shoutcast_password,
  mount="",
  source
)