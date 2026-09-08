"""Un URL di Drive nasce in un posto solo, e quel posto sa elencare solo dei figli.

Spec 9C non chiede una convenzione, chiede un meccanismo. La lettura da Drive parte
sempre da una cartella che il titolare ha indicato -- `google_drive_accounts.
root_folder_ids` -- e "elenca i figli di questa cartella" e' l'unica interrogazione
che il sistema ha bisogno di fare. Una ricerca aperta (`name contains '...'`)
attraverserebbe l'intero Drive dell'utente, comprese le cartelle che non ci ha mai
dato, quindi non deve essere *scomoda*: deve essere impossibile da costruire.

Come per Gmail (`test_gmail_query.py`, di cui questo file e' il gemello), le guardie
sono due, perche' ognuna da sola e' a una modifica di distanza dall'essere aggirata:

1. `files_list_url` **rifiuta** un `q` che non contenga una clausola `'<id>' in
   parents` ben formata, e ne rifiuta uno che contenga `contains`. Il bug non e'
   sconsigliato: e' non costruibile.
2. `test_no_other_module_can_build_a_drive_url` cammina l'AST di ogni file sorgente e
   fallisce se un literal contiene l'host di Drive, quello di upload o un path
   `/files`. La guardia 1 e' a una riga dall'essere cancellata; la guardia 2 e' cio'
   che rende quella cancellazione insufficiente, perche' chi vuole bypassare questo
   modulo deve pur scrivere un URL da qualche parte e non gli resta nessun posto dove
   scriverlo.

L'insieme delle eccezioni della guardia 2 e' **vuoto**: `storage/gdrive.py`, che gli
URL di Drive li scriveva a mano, e' stato migrato a chiamare questo modulo (9C T1,
ruling 4) invece di essere messo in una lista di deroghe.
"""

import ast
import inspect
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from pigrocrm.core.drive import query as module
from pigrocrm.core.drive.query import (
    DRIVE_API_ROOT,
    checked_outside_id,
    children_query,
    escape_query_value,
    file_export_url,
    file_media_url,
    file_meta_url,
    file_url,
    files_by_app_property_url,
    files_create_url,
    files_list_url,
    folder_by_name_query,
    upload_create_url,
    upload_media_url,
)
from pigrocrm.core.errors import ValidationFailed

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOTS = (
    REPO_ROOT / "packages" / "core" / "src",
    REPO_ROOT / "apps" / "api" / "src",
    REPO_ROOT / "apps" / "mcp" / "src",
)
QUERY_MODULE = REPO_ROOT / "packages" / "core" / "src" / "pigrocrm" / "core" / "drive" / "query.py"
# Uno qualsiasi di questi in un literal significa che qualcuno sta assemblando a mano
# un URL di Drive. `/files` prende anche `f"{DRIVE_API_ROOT}/files?q=..."`, che
# sfuggirebbe a una scansione del solo host; `googleapis.com/upload` prende l'endpoint
# di upload, che vive su un path diverso dallo stesso host.
URL_FRAGMENTS = ("googleapis.com/drive", "googleapis.com/upload", "/files")

# Vuoto, e deve restarlo. `storage/gdrive.py` era l'unico candidato a un'eccezione ed
# e' stato migrato (ruling 4 di 9C T1): dichiarare una deroga per l'unico modulo che
# oggi tocca Drive avrebbe reso la guardia una formalita' proprio nel file dove
# qualcuno aggiungera' la prossima chiamata. Le coppie sono `(file, literal)` esatte,
# non file interi, cosi' che un *secondo* literal nello stesso modulo fallisca comunque;
# e sono ricontrollate sotto, cosi' che una voce stantia non sopravviva in silenzio a
# cio' che descriveva.
ALLOWED_LITERALS: frozenset[tuple[Path, str]] = frozenset()

FOLDER = "1AbCdEfGhIjKlMnOpQ"


# --- l'unica interrogazione che serve: i figli di una cartella -----------------------


def test_children_query_names_one_folder_and_excludes_the_trash() -> None:
    assert children_query(FOLDER) == f"'{FOLDER}' in parents and trashed = false"


def test_a_folder_id_that_could_break_out_of_the_query_is_refused() -> None:
    """L'id arriva da `google_drive_accounts.root_folder_ids`, cioe' in ultima analisi
    da un incollaggio del titolare: un apice chiuderebbe la clausola e il resto
    diventerebbe un'espressione di ricerca scelta da chi ha incollato."""
    hostile = [
        "1AbCdEfGhIjKlMnOpQ' or name contains 'fattura",
        "1AbCdEfGhIjKlMnOpQ or trashed = true",
        "1AbCdEfGhIjKlMnOpQ ",
        "1AbCd/EfGhIjKlMnOpQ",
        "../../drives",
        "",
        # Troppo corto per essere un id di Drive: gli id veri stanno fra 28 e 44
        # caratteri, e accettarne uno di tre significa accettare qualunque parola.
        "abc",
        "x" * 129,
    ]
    for folder_id in hostile:
        with pytest.raises(ValidationFailed) as caught:
            children_query(folder_id)
        assert caught.value.details["field"] == "folder_id"


def test_checked_outside_id_names_the_field_it_was_given() -> None:
    """Lo stesso controllo, due nomi. Un id che arriva da fuori puo' essere la cartella
    radice incollata dal titolare o il file che un agente ha chiesto di leggere, e la
    forma pretesa e' identica -- ma il messaggio no: chi legge «non e\' un id di
    cartella Drive» dopo aver passato l'id di un *file* va a cercare l'errore nella
    configurazione delle radici invece che nel parametro che ha scritto lui.
    """
    assert checked_outside_id(FOLDER, field="folder_id") == FOLDER
    assert checked_outside_id(FOLDER, field="file_id") == FOLDER

    with pytest.raises(ValidationFailed) as as_file:
        checked_outside_id("abc", field="file_id")
    assert as_file.value.details["field"] == "file_id"
    assert as_file.value.details["entity"] == "drive_query"

    with pytest.raises(ValidationFailed) as as_folder:
        checked_outside_id("abc", field="folder_id")
    assert as_folder.value.details["field"] == "folder_id"
    # Una sola frase per i due, e che non nomini nessuno dei due tipi: e' la forma
    # dell'id che e' sbagliata, non cosa c'e' dall'altra parte.
    assert as_file.value.details["reason"] == as_folder.value.details["reason"]
    assert "cartella" not in as_file.value.details["reason"]


def test_checked_outside_id_is_the_check_children_query_already_did() -> None:
    """La stessa severita' di prima, non una nuova: gli id che `children_query`
    rifiutava restano rifiutati, e con lo stesso `field`."""
    for hostile in ("", "abc", "1AbCd/EfGhIjKlMnOpQ", "x" * 129, "1AbCdEfGhIjKlMnOpQ "):
        with pytest.raises(ValidationFailed) as caught:
            checked_outside_id(hostile, field="folder_id")
        assert caught.value.details["field"] == "folder_id"
        with pytest.raises(ValidationFailed):
            children_query(hostile)


# --- guardia uno: l'URL di elenco rifiuta tutto cio' che non sia un elenco di figli --


def test_the_list_url_refuses_a_query_that_is_not_scoped_to_a_folder() -> None:
    """Guardia uno. La sola funzione che sa costruire un `files.list` non ne costruisce
    uno che non sia limitato a una cartella data: cosi' "leggere tutto il Drive" non e'
    sconsigliato, e' non costruibile."""
    unscoped = [
        "",
        "   ",
        "trashed = false",
        "mimeType='application/pdf'",
        "name='fattura.pdf'",
        # La forma dell'id conta, non la presenza delle parole: `in parents` senza una
        # clausola ben formata davanti non limita niente.
        "in parents",
        "'' in parents",
        "'1AbCd EfGhIjKlMnOpQ' in parents",
    ]
    for bad in unscoped:
        with pytest.raises(ValidationFailed, match="cartella"):
            files_list_url(bad, fields="files(id)")


def test_the_list_url_refuses_a_full_text_search_even_inside_a_folder() -> None:
    """`contains` e' l'operatore di ricerca libera di Drive. Anche ristretto a una
    cartella non e' cio' che l'import fa -- l'import elenca e decide dopo -- e
    ammetterlo qui vorrebbe dire ammettere che una stringa di ricerca arrivi da fuori."""
    for bad in [
        f"'{FOLDER}' in parents and name contains 'fattura'",
        f"'{FOLDER}' in parents and fullText contains 'fattura'",
        f"'{FOLDER}' in parents and name CONTAINS 'fattura'",
    ]:
        with pytest.raises(ValidationFailed, match="contains"):
            files_list_url(bad, fields="files(id)")


def test_the_list_url_refuses_a_query_that_widens_past_its_folder() -> None:
    """Che una clausola `in parents` ci sia non basta: deve essere l'unica cosa che
    decide *dove* si guarda. `'<id>' in parents or mimeType='application/pdf'` contiene
    la clausola e ciononostante elenca ogni PDF del Drive, quindi un controllo di sola
    presenza renderebbe falso il docstring di questo modulo. Un elenco puo' solo
    restringere: `or`, `not` e le parentesi -- che servono a raggruppare un `or` -- sono
    i tre modi di allargare, e sono rifiutati tutti e tre."""
    for bad in [
        children_query(FOLDER) + " or mimeType='application/pdf'",
        f"not {children_query(FOLDER)}",
        f"'{FOLDER}' in parents and not mimeType='application/pdf'",
        f"'{FOLDER}' in parents OR '{FOLDER}' in parents",
        f"('{FOLDER}' in parents)",
        f"'{FOLDER}' in parents and (trashed = false or trashed = true)",
    ]:
        with pytest.raises(ValidationFailed, match="allarga"):
            files_list_url(bad, fields="files(id)")


def test_a_value_in_quotes_is_never_mistaken_for_an_operator() -> None:
    """I controlli girano su uno scheletro in cui ogni literal fra apici e' stato
    svuotato, e non sul `q` grezzo. Non e' una raffinatezza: la ragione sociale di un
    cliente diventa un segmento di storage key, quindi un nome di cartella, quindi un
    valore dentro `name='...'` -- e "Contains S.r.l." avrebbe fatto fallire *ogni* put e
    ogni get di quel cliente con un `ValidationFailed` su un `q` che il CRM aveva
    costruito lui. Il rifiuto vale per l'operatore, non per la parola."""
    assert files_list_url(folder_by_name_query("id2", "contains-srl-01234567"), fields="files(id)")
    assert files_list_url(folder_by_name_query("id2", "or-not-spa"), fields="files(id)")
    # Apice compreso: lo scheletro deve saltare anche un apice escapato, altrimenti
    # perderebbe il conto delle virgolette proprio sul valore piu' ostile.
    assert files_list_url(
        folder_by_name_query("id2", "bar's or fullText contains x"), fields="files(id)"
    )
    # E fuori dagli apici l'operatore resta vietato.
    with pytest.raises(ValidationFailed, match="contains"):
        files_list_url(f"'{FOLDER}' in parents and name contains 'x'", fields="files(id)")


def test_the_list_url_accepts_a_query_that_is_scoped_and_says_where_it_is_going() -> None:
    url = files_list_url(children_query(FOLDER), page_token="tok", fields="files(id,name)")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "www.googleapis.com"
    assert parsed.path == "/drive/v3/files"
    assert query["q"] == [f"'{FOLDER}' in parents and trashed = false"]
    assert query["pageToken"] == ["tok"]
    assert query["fields"] == ["files(id,name)"]
    # Una cartella di un titolare vive su un Drive condiviso quanto una di un service
    # account: senza questi due parametri Drive risponde 404 a entrambe.
    assert query["supportsAllDrives"] == ["true"]
    assert query["includeItemsFromAllDrives"] == ["true"]


def test_the_first_page_has_no_page_token_at_all() -> None:
    assert "pageToken" not in files_list_url(children_query(FOLDER), fields="files(id)")


def test_every_query_this_module_builds_is_one_it_would_also_accept() -> None:
    """Le due guardie devono essere d'accordo. Un costruttore che producesse un `q` che
    il costruttore di URL poi rifiuta fallirebbe al primo import, non qui."""
    assert files_list_url(children_query(FOLDER), fields="files(id)")
    assert files_list_url(folder_by_name_query(FOLDER, "acme-01234567"), fields="files(id)")
    # Anche con un id corto: quelli che `_ensure_folder` si passa arrivano da Drive
    # stesso, non da un incollaggio, e sono opachi per contratto.
    assert files_list_url(folder_by_name_query("id2", "acme-01234567"), fields="files(id)")


# --- la cartella per nome: placement, e l'unica interrogazione con un valore dentro --


def test_folder_by_name_query_is_scoped_named_and_typed() -> None:
    assert folder_by_name_query("id2", "acme-01234567") == (
        "trashed=false and name='acme-01234567' and 'id2' in parents "
        "and mimeType='application/vnd.google-apps.folder'"
    )


def test_a_folder_name_is_escaped_rather_than_refused() -> None:
    """Il nome e' un segmento di storage key generato dal CRM, non testo dell'utente:
    la sua classe di caratteri oggi non contiene ne' apice ne' backslash. L'escaping
    resta perche' un allargamento futuro di quella classe non deve riaprire in silenzio
    l'injection solo perche' oggi nessuno la esercita."""
    assert "name='bar\\'s'" in folder_by_name_query("id2", "bar's")


def test_escaping_handles_the_backslash_before_the_quote() -> None:
    """Invertire l'ordine lascerebbe un backslash solitario in grado di mangiarsi
    l'apice di chiusura del filtro: e' lo stesso motivo per cui gli escaper dei
    template lo fanno in questo ordine."""
    assert escape_query_value("bar's") == "bar\\'s"
    assert escape_query_value("a\\b") == "a\\\\b"
    assert escape_query_value("a\\'b") == "a\\\\\\'b"


# --- l'identita': appProperties, l'eccezione dichiarata alla guardia uno -------------


def test_the_app_property_url_asks_for_one_exact_key_across_every_drive() -> None:
    """L'unica interrogazione non limitata a una cartella, e lo e' perche' e' *piu'*
    specifica, non meno: nomina un valore che il CRM ha scritto lui stesso in
    `appProperties`, non una ricerca del Drive. Stessa logica dell'eccezione
    `rfc822msgid` di Gmail. La forma della clausola e' esatta perche' e' quella che
    `FakeDrive._list` sa leggere, oltre che quella che Drive accetta."""
    url = files_by_app_property_url(
        "pigrocrm_key", "acme-01234567/0199abcd/v1.pdf", fields="files(id)"
    )
    query = parse_qs(urlparse(url).query)
    assert query["q"] == [
        "trashed=false and appProperties has "
        "{ key='pigrocrm_key' and value='acme-01234567/0199abcd/v1.pdf' }"
    ]
    assert query["corpora"] == ["allDrives"]
    assert query["includeItemsFromAllDrives"] == ["true"]
    assert query["supportsAllDrives"] == ["true"]


def test_the_app_property_value_is_escaped_not_interpolated_raw() -> None:
    url = files_by_app_property_url("pigrocrm_key", "bar's", fields="files(id)")
    assert "value='bar\\'s'" in parse_qs(urlparse(url).query)["q"][0]


def test_an_app_property_key_that_is_not_a_plain_name_is_refused() -> None:
    """La chiave e' una costante del codice, non un input: verificarla costa una riga e
    rende impossibile che diventi un input per distrazione."""
    for hostile in ["pigrocrm_key' and name contains 'x", "", "chiave con spazi"]:
        with pytest.raises(ValidationFailed) as caught:
            files_by_app_property_url(hostile, "v1.pdf", fields="files(id)")
        assert caught.value.details["field"] == "key"


def test_the_strict_list_url_would_have_refused_the_app_property_query() -> None:
    """Perche' esiste un secondo costruttore invece di un parametro `strict=False`: la
    deroga e' un'altra funzione, con un altro nome, che dice nel nome cosa filtra."""
    with pytest.raises(ValidationFailed):
        files_list_url(
            "trashed=false and appProperties has { key='pigrocrm_key' and value='v1.pdf' }",
            fields="files(id)",
        )


# --- gli URL per un singolo file -----------------------------------------------------


def test_the_single_file_urls_carry_the_id_in_the_path_and_all_drives_support() -> None:
    assert file_url("id2") == f"{DRIVE_API_ROOT}/files/id2?supportsAllDrives=true"
    assert file_media_url("id2") == f"{DRIVE_API_ROOT}/files/id2?supportsAllDrives=true&alt=media"
    meta = parse_qs(urlparse(file_meta_url("id2", fields="id,driveId")).query)
    assert meta["fields"] == ["id,driveId"]
    assert meta["supportsAllDrives"] == ["true"]
    assert meta["includeItemsFromAllDrives"] == ["true"]


def test_the_export_url_asks_for_a_conversion_and_defaults_to_plain_text() -> None:
    """`files.export` e' il solo endpoint qui senza `supportsAllDrives`: non e' un suo
    parametro (il client generato di Google non lo espone), e passarne uno che l'API
    non documenta e' un 400 in attesa di succedere. Un Google Doc su uno Shared Drive
    si esporta comunque, perche' l'accesso e' per fileId."""
    url = file_export_url("id2")
    assert urlparse(url).path == "/drive/v3/files/id2/export"
    assert parse_qs(urlparse(url).query) == {"mimeType": ["text/plain"]}
    assert parse_qs(urlparse(file_export_url("id2", "text/csv")).query)["mimeType"] == ["text/csv"]


def test_an_export_mime_type_that_is_not_one_is_refused() -> None:
    for hostile in ["text/plain&alt=media", "not a mime", "", "text/plain "]:
        with pytest.raises(ValidationFailed) as caught:
            file_export_url("id2", hostile)
        assert caught.value.details["field"] == "mime"


def test_a_file_id_that_is_not_one_is_refused_by_every_path_builder() -> None:
    """Questi id arrivano dall'elenco di Drive stesso, quindi uno ostile significa che
    la risposta e' stata manomessa -- ma il path traversal verso un altro endpoint
    costa una riga da rendere impossibile e molto da scoprire dopo."""
    for hostile in ["../../drives/other", "id 2", "id/2", "", "x" * 129]:
        for builder in (file_url, file_media_url, file_export_url, upload_media_url):
            with pytest.raises(ValidationFailed):
                builder(hostile)
        with pytest.raises(ValidationFailed):
            file_meta_url(hostile, fields="id")


# --- la scrittura: create e upload ---------------------------------------------------


def test_the_create_and_upload_urls_say_which_upload_they_are() -> None:
    assert files_create_url(fields="id") == (
        f"{DRIVE_API_ROOT}/files?supportsAllDrives=true&fields=id"
    )
    multipart = parse_qs(urlparse(upload_create_url(fields="id")).query)
    assert multipart["uploadType"] == ["multipart"]
    assert multipart["supportsAllDrives"] == ["true"]
    assert urlparse(upload_create_url(fields="id")).path == "/upload/drive/v3/files"
    media = urlparse(upload_media_url("id2"))
    assert media.path == "/upload/drive/v3/files/id2"
    assert parse_qs(media.query)["uploadType"] == ["media"]


def test_no_helper_takes_a_caller_supplied_search_string() -> None:
    """Nessuna superficie di questa slice accetta una stringa di ricerca di Drive. Il
    modulo espone esattamente questi costruttori, e il solo che prende un `q` --
    `files_list_url` -- rifiuta tutto cio' che non abbia costruito questo modulo
    stesso. Elencare i nomi qui rende l'aggiunta di un `search_url(text)` una modifica
    che qualcuno deve *decidere* di fare, non una che passa in un diff."""
    exported = sorted(
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and inspect.isfunction(value)
        # Definite qui, non solo importate qui: `urlencode` e' una funzione pubblica
        # nel namespace di questo modulo e non ha niente a che vedere con la superficie
        # che stiamo fissando.
        and value.__module__ == module.__name__
    )
    assert exported == [
        "checked_outside_id",
        "children_query",
        "escape_query_value",
        "file_export_url",
        "file_media_url",
        "file_meta_url",
        "file_url",
        "files_by_app_property_url",
        "files_create_url",
        "files_list_url",
        "folder_by_name_query",
        "upload_create_url",
        "upload_media_url",
    ]


# --- guardia due: nessun altro modulo puo' scrivere uno di questi URL ---------------


def _string_constants(path: Path) -> list[str]:
    """Solo i literal di stringa, dall'AST.

    Non un `grep`: questo file, il docstring del modulo e mezzi commenti della slice
    parlano di `/files` in prosa, e una scansione incapace di distinguere una frase da
    un URL sarebbe o abbastanza rumorosa da venire disattivata o abbastanza ristretta
    da essere inutile.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_no_other_module_can_build_a_drive_url() -> None:
    """Guardia due. Che `files_list_url` rifiuti un `q` non limitato a una cartella
    vale esattamente quanto la garanzia che sia l'unico modo di arrivare a
    `files.list`: altrimenti il prossimo chiamante si scrive la sua f-string e il
    rifiuto protegge una funzione che nessuno chiama.

    I docstring sono inclusi per la forma stessa della camminata sull'AST: sono
    `ast.Constant` anche loro, quindi un modulo che si limitasse a *documentare*
    l'endpoint fallirebbe. E' deliberato e costa poco da soddisfare -- si scrive
    `files.list` invece del path, o si nomina l'helper -- ed e' il prezzo di non dover
    distinguere un URL da una frase che ne parla.
    """
    offenders: list[str] = []
    for root in SOURCE_ROOTS:
        # Una scansione che non guarda nessun file passa sempre. Se un giorno un
        # package si sposta, questo test deve fallire per quello, non diventare verde
        # per vuoto.
        assert list(root.rglob("*.py")), root
        for path in sorted(root.rglob("*.py")):
            if path == QUERY_MODULE:
                continue
            for literal in _string_constants(path):
                if (path, literal) in ALLOWED_LITERALS:
                    continue
                for fragment in URL_FRAGMENTS:
                    if fragment in literal:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}: {literal!r}")
    assert offenders == [], (
        "solo drive/query.py può costruire un URL di Drive: un elenco costruito "
        "altrove sfugge al vincolo di restare dentro una cartella indicata dal "
        "titolare (spec 9C). Usa children_query / files_list_url / file_meta_url / "
        "file_media_url / file_export_url / files_by_app_property_url / "
        "files_create_url / upload_create_url / upload_media_url.\n" + "\n".join(offenders)
    )


def test_every_allowed_literal_is_still_present_in_that_file() -> None:
    """La guardia della lista di deroghe. Una voce sopravvissuta a cio' che descriveva
    allargherebbe il punto cieco della scansione di esattamente un literal, nel file
    dove qualcuno ha piu' probabilita' di aggiungere una chiamata a Drive. Oggi la
    lista e' vuota e questo test non ha niente da fare: e' qui perche' il giorno in cui
    qualcuno aggiunge una deroga, la deroga nasca gia' con il suo controllo di
    scadenza."""
    for path, literal in ALLOWED_LITERALS:
        assert path.exists(), f"{path} non esiste piu': l'eccezione va rimossa"
        assert literal in _string_constants(path), (
            f"{path.relative_to(REPO_ROOT)} non contiene piu' {literal!r}: "
            "l'eccezione va rimossa insieme al codice che la giustificava"
        )


def test_the_guard_above_would_notice_a_hand_built_drive_url(tmp_path: Path) -> None:
    """Una scansione che non puo' fallire e' una scansione di cui nessuno si accorgera'
    che si e' rotta. Questa fa girare lo stesso lettore su un file che fa esattamente
    quello che la guardia vieta."""
    offender = tmp_path / "importer.py"
    offender.write_text(
        "URL = \"https://www.googleapis.com/drive/v3/files?q=name contains 'fattura'\"\n"
        'UP = "https://www.googleapis.com/upload/drive/v3/files?uploadType=media"\n',
        encoding="utf-8",
    )
    literals = _string_constants(offender)
    assert sum(fragment in literal for literal in literals for fragment in URL_FRAGMENTS) == 4, (
        literals
    )
