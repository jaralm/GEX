"""
Safe GitHub Actions entrypoint for the MEFF daily pipeline.

The dashboard data must still be generated if the optional Gmail notification
fails because of credentials, SMTP availability, or Gmail-side limits.
"""

import meff_opciones


_original_enviar_email = meff_opciones.enviar_email


def enviar_email_seguro(texto):
    try:
        _original_enviar_email(texto)
    except Exception as exc:
        print(f"AVISO: email no enviado ({exc}). El pipeline continua.")


meff_opciones.enviar_email = enviar_email_seguro


if __name__ == "__main__":
    meff_opciones.main()
