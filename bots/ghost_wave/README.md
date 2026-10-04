# Ghost Wave Bot

Bot independiente para administrar oleadas de fantasmas mediante el buzón de Highrise.

Funciones:
- Intervalo predeterminado de 75 minutos.
- Aviso 5 minutos antes.
- Confirmación de la hora real de activación.
- Recalculo desde la hora real + intervalo.
- Pausar y reanudar con nueva configuración.
- Varias salas con enlaces y Room ID.
- Invitación de Highrise cuando existe una conversación privada y Room ID.
- Suscriptores separados de administradores.
- Persistencia en JSON.
- Administración exclusivamente por mensajes privados.

Accesos:
- El propietario da/quita administradores.
- El propietario autoriza/quita suscriptores.
- Los administradores configuran horas, intervalo y salas.
- Los suscriptores reciben los avisos.
