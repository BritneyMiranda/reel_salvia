"""hacer_reel.py con dos agregados: fotos de fondo por escena y música bajo la voz.

    python hacer_reel_salvia.py --voz mi_voz.m4a --autor "Nombre" --fuente "Infobae" \
        --fotos a.jpg b.webp c.avif --musica fondo.mp3

Usa reel.py sin cambios: solo reemplaza el cuadro de fondo (_cuadro) y mezcla la música al final.
Guarda en salidas/: reel.mp4 (solo voz), reel_musica.mp4, reel.wav, reel.srt, portada.png y posts.md.
"""
import argparse
import json
import subprocess
import time

from PIL import Image, ImageDraw, ImageFilter

import reel

PANEO = 90          # píxeles que se desplaza la foto durante una escena
OSCURO = 0.62       # cuánto se tapa la foto con el color de fondo (0 = foto pura, 1 = sin foto)


def cargar_foto(ruta):
    """jpg, png, webp o avif; si Pillow no abre el avif, lo convierte ffmpeg."""
    try:
        return Image.open(ruta).convert("RGB")
    except Exception:
        png = reel.Path(reel.AQUI / "salidas" / (reel.Path(ruta).stem + ".png"))
        subprocess.run([reel.FFMPEG, "-y", "-v", "error", "-i", str(ruta), str(png)], check=True)
        return Image.open(png).convert("RGB")


def fondo(foto):
    """Foto a pantalla completa (un poco más alta, para el paneo), suavizada y oscurecida hacia abajo."""
    alto = reel.ALTO + PANEO
    escala = max(reel.ANCHO / foto.width, alto / foto.height)
    f = foto.resize((round(foto.width * escala), round(foto.height * escala)), Image.LANCZOS)
    x, y = (f.width - reel.ANCHO) // 2, (f.height - alto) // 2
    f = f.crop((x, y, x + reel.ANCHO, y + alto)).filter(ImageFilter.GaussianBlur(2))
    velo = Image.new("RGB", f.size, reel.FONDO)
    # más oscuro arriba (título) y abajo (subtítulos y fuente) que en el centro
    mascara = Image.linear_gradient("L").resize((1, 3)).resize((1, alto))
    mascara = Image.eval(mascara, lambda v: int(255 * (OSCURO + (1 - OSCURO) * 0.55 * abs(v - 128) / 128)))
    return Image.composite(velo, f, mascara.resize(f.size))


def textos_fijos(titulo, fuente_datos, autor):
    """Lo mismo que reel._base (título, aviso de IA, fuente), pero sobre una capa transparente."""
    img = Image.new("RGBA", (reel.ANCHO, reel.ALTO), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((reel.MARGEN, 250), titulo.upper(), font=reel._fuente("PublicSans", 40, 800), fill=reel.ACENTO)
    aviso = "VOZ GENERADA CON IA"
    f = reel._fuente("PublicSans", 28, 700)
    x1 = reel.MARGEN + d.textlength(aviso, font=f) + 36
    d.rounded_rectangle((reel.MARGEN, 315, x1, 365), radius=25, outline=reel.SUAVE, width=2)
    d.text((reel.MARGEN + 18, 340), aviso, font=f, fill=reel.SUAVE, anchor="lm")
    pie = reel._fuente("PublicSans", 32, 500)
    for i, linea in enumerate(reel._envolver(d, f"{autor} · Fuente: {fuente_datos}", pie, reel.ANCHO - 2 * reel.MARGEN)):
        d.text((reel.MARGEN, 1490 + i * 44), linea, font=pie, fill=reel.SUAVE)
    return img


def con_fotos(fondos, capa_fija):
    """Reemplaza el fondo liso de reel._cuadro por la foto de la escena, con paneo y fundido entre escenas."""
    original = reel._cuadro

    def recorte(i, t, narracion):
        ini, fin = narracion.escenas[i]
        avance = min(1.0, max(0.0, (t - ini + reel.PAUSA) / (fin - ini + 2 * reel.PAUSA)))
        y = int(PANEO * (1 - avance)) if i % 2 else int(PANEO * avance)   # una escena baja, la otra sube
        return fondos[i % len(fondos)].crop((0, y, reel.ANCHO, y + reel.ALTO))

    def cuadro(base, capas, narracion, t, bloques, fuente_sub):
        i = max([k for k, (ini, _) in enumerate(narracion.escenas) if ini - reel.PAUSA <= t] or [0])
        img = recorte(i, t, narracion)
        a = (t - narracion.escenas[i][0] + reel.PAUSA) / 0.5
        if i > 0 and a < 1:
            img = Image.blend(recorte(i - 1, t, narracion), img, max(0.0, a))
        img.paste(capa_fija, (0, 0), capa_fija)
        return original(img, capas, narracion, t, bloques, fuente_sub)

    reel._cuadro = cuadro


def con_musica(video, musica, salida, volumen_lufs=-30):
    """Música a -30 LUFS que baja cuando hay voz (sidechain), con fundidos; el total queda en -14 LUFS."""
    dur = reel.sf.info(reel.Path(video).with_suffix(".wav")).duration   # reel.video deja la narración al lado
    filtro = (f"[0:a]asplit[voz][guia];"
              f"[1:a]loudnorm=I={volumen_lufs},aresample=48000,afade=t=in:d=1.5,"
              f"afade=t=out:st={dur - 3:.2f}:d=3[m];"
              f"[m][guia]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=600[mb];"
              f"[voz][mb]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    subprocess.run([reel.FFMPEG, "-y", "-v", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(musica),
                    "-filter_complex", filtro, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
                    str(salida)], check=True)
    return salida


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--voz", required=True)
    p.add_argument("--autor", required=True)
    p.add_argument("--fuente", required=True)
    p.add_argument("--fotos", nargs="+", required=True, help="una por escena; si hay menos, se repiten en orden")
    p.add_argument("--musica", required=True)
    p.add_argument("--device", default="cpu")
    p.add_argument("--tts", default="Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    p.add_argument("--velocidad", type=float, default=1.0)
    p.add_argument("--salidas", default=str(reel.AQUI / "salidas"))
    a = p.parse_args()

    t0 = time.time()
    salidas = reel.Path(a.salidas)
    archivo_guion = salidas / "guion.json"
    guion = json.loads(archivo_guion.read_text(encoding="utf-8"))

    con_fotos([fondo(cargar_foto(f)) for f in a.fotos], textos_fijos(guion["titulo"], a.fuente, a.autor))

    voz = reel.Voz(a.voz, modelo=a.tts, device=a.device)
    reel._reloj(f"voz cargada; referencia: «{voz.texto_ref}»", t0)
    narracion = reel.narrar(voz, guion, velocidad=a.velocidad)
    archivo_guion.write_text(json.dumps(guion, ensure_ascii=False, indent=2), encoding="utf-8")
    reel._reloj(f"narración: {narracion.duracion:.1f} s; WER por escena: "
                + ", ".join(f"{e['wer']:.2f}" for e in guion["escenas"]), t0)

    reel.subtitulos(narracion, guion)
    reel.a_srt(narracion, salidas / "reel.srt")
    reel._reloj(f"subtítulos: {len(narracion.palabras)} palabras", t0)

    reel.portada(guion, narracion, salidas / "portada.png", a.fuente, a.autor)
    reel.video(guion, narracion, salidas / "reel.mp4", a.fuente, a.autor)
    con_musica(salidas / "reel.mp4", a.musica, salidas / "reel_musica.mp4")
    reel.posts(guion, salidas / "posts.md")
    reel._reloj(f"listo: {salidas / 'reel_musica.mp4'}", t0)
