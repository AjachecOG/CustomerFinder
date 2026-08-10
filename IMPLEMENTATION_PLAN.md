# Customer Finder — plan implementacji MVP v1

Status dokumentu: gotowy do wykonania  
Docelowy wykonawca: autonomiczny agent programistyczny o ograniczonej zdolności podejmowania decyzji  
Język implementacji: Python 3.12  
Główny system operacyjny użytkownika: Windows / PowerShell  
Środowiska uruchomieniowe: lokalnie, Docker, agent chmurowy po sklonowaniu repozytorium

## 1. Cel i definicja produktu

Zbudować narzędzie CLI, które dla punktu geograficznego, promienia i listy kategorii wyszukuje lokalne kawiarnie, cukiernie, piekarnie, lodziarnie i podobne firmy, które prawdopodobnie nie posiadają własnej sensownej strony WWW.

Przykładowe wywołanie:

```powershell
finder search `
  --lat 51.1079 `
  --lon 17.0385 `
  --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --enrich none `
  --output out/leads_wroclaw.csv
```

Podstawowym źródłem danych jest Overture Maps Places. Opcjonalne sprawdzenie Google korzysta wyłącznie z oficjalnego Places API (New). Playwright, scrapowanie Google Maps, rozszerzenie Chrome, automatyczna wysyłka ofert, panel WWW i PostgreSQL nie należą do MVP v1.

Narzędzie nie może twierdzić, że udowodniło nieistnienie strony. Poprawna interpretacja wyniku `likely_no_site` brzmi: „w użytych źródłach nie znaleziono własnej domeny”.

## 2. Nienegocjowalne decyzje architektoniczne

Agent wykonujący plan nie może zmieniać poniższych decyzji bez wyraźnej zgody właściciela projektu.

1. Python 3.12, bez Node.js jako drugiego runtime.
2. CLI zbudowane w Typer.
3. Modele i walidacja w Pydantic v2.
4. Zapytania do Overture wykonywane przez DuckDB na zdalnych plikach GeoParquet.
5. Dokładny promień liczony funkcją haversine w Pythonie. Rozszerzenie DuckDB
   `spatial` wolno użyć wyłącznie do `ST_X/ST_Y` przy ekstrakcji punktu z geometrii;
   nie używać `ST_Distance` na długości i szerokości geograficznej.
6. Najpierw filtr bounding box w DuckDB, potem dokładny filtr promienia w Pythonie.
7. Overture jest źródłem trwałego CSV. Surowe pola Google nie są zapisywane w CSV; domyślnie można przechować jedynie `place_id` oraz ręczną decyzję użytkownika.
8. Google enrichment jest opcjonalny, domyślnie wyłączony i używa Text Search (New), nie Legacy Find Place i nie Playwrighta.
9. Brak klucza Google przy `--enrich google` jest błędem konfiguracji. Program nie może po cichu przełączyć się na inny tryb.
10. Pole `brand` ani niski `confidence` nie powodują automatycznego usunięcia rekordu. Wpływają na scoring lub bucket `unknown`.
11. Każdy rekord zachowuje identyfikator Overture, wersję wydania oraz informacje o źródłach i licencjach.
12. Każde uruchomienie `search`, które przeszło parsowanie CLI i ma poprawnie
    wyznaczoną ścieżkę outputu, tworzy obok CSV manifest sukcesu albo błędu.
    Błędy samego parsera przed utworzeniem `run_id` nie mają gdzie zapisać manifestu.
13. Wynik jest zapisywany atomowo: najpierw plik tymczasowy, następnie zmiana nazwy. Nie pozostawiać częściowego CSV jako wyniku sukcesu.
14. Agent nie może przejść do kolejnego etapu, dopóki testy i bramka akceptacyjna bieżącego etapu nie przejdą.

## 3. Zakres MVP

### 3.1 W zakresie

- wyszukiwanie po `lat`, `lon` i `radius-km`;
- kategorie wskazane przez aliasy z wbudowanego `customer_finder/config/categories.yml`;
- pobieranie bieżącego albo jawnie wskazanego wydania Overture;
- filtrowanie kategorii po `basic_category` i `taxonomy`;
- normalizacja strony, social mediów, agregatorów i kontaktów;
- deduplikacja;
- rozpoznanie sieciówek;
- deterministyczny scoring bez AI;
- buckety `has_owned_site`, `social_only`, `aggregator_only`, `likely_no_site`, `unknown`;
- CSV, manifest JSON i plik linków do ręcznej weryfikacji;
- opcjonalny Google Places Text Search z limitem kosztowym;
- testy jednostkowe, integracyjne na fixtures i opcjonalne smoke testy sieciowe;
- Docker i instrukcja PowerShell.

### 3.2 Poza zakresem

- dzielnice i dowolne polygony; będą etapem v1.1;
- automatyczne przeszukiwanie całego miasta siatką;
- przeglądarkowe scrapowanie map;
- oceny i recenzje Google;
- automatyczne wysyłanie e-maili, SMS-ów lub wykonywanie połączeń;
- CRM, panel WWW, konta użytkowników;
- cykliczne zadania i harmonogram;
- trenowanie modelu ML lub używanie LLM do klasyfikacji;
- samodzielne geokodowanie tekstowego adresu w v1.

## 4. Struktura repozytorium

Agent ma utworzyć dokładnie tę strukturę. Nie dodawać nowych warstw typu `services`, `managers` lub `repositories`, jeśli nie są wymagane przez plan.

```text
CustomerFinder/
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
├── IMPLEMENTATION_PLAN.md
├── pyproject.toml
├── src/
│   └── customer_finder/
│       ├── __init__.py
│       ├── cli.py
│       ├── settings.py
│       ├── models.py
│       ├── errors.py
│       ├── geometry.py
│       ├── overture.py
│       ├── normalize.py
│       ├── deduplicate.py
│       ├── classify.py
│       ├── scoring.py
│       ├── google_places.py
│       ├── calibration.py
│       ├── verify_links.py
│       ├── output.py
│       ├── pipeline.py
│       └── config/
│           ├── categories.yml
│           ├── chain_denylist.yml
│           ├── domain_rules.yml
│           └── taxonomy_snapshot.yml
├── tests/
│   ├── fixtures/
│   │   ├── overture_places.parquet
│   │   ├── google_text_search_match.json
│   │   ├── google_text_search_ambiguous.json
│   │   ├── expected_leads.csv
│   │   └── calibration_reviewed.csv
│   ├── unit/
│   ├── integration/
│   └── conftest.py
└── out/
    └── .gitkeep
```

`out/*` musi być ignorowane przez Git z wyjątkiem `.gitkeep`. Konfiguracje wbudowane
ładować przez `importlib.resources`, dzięki czemu działają po instalacji wheel i w
Dockerze. Opcjonalne `--config-dir PATH` nadpisuje cały zestaw czterech plików YAML;
brak któregokolwiek pliku w podanym katalogu jest błędem konfiguracji, bez mieszania
plików wbudowanych i użytkownika.

## 5. Zależności

W `pyproject.toml` należy przypiąć kompatybilne zakresy wersji, nie używać nieograniczonego `*`.

Zależności runtime:

- `typer` — CLI;
- `pydantic` i `pydantic-settings` — modele i konfiguracja;
- `duckdb` — odczyt GeoParquet;
- `httpx` — STAC i Google API;
- `PyYAML` — konfiguracja kategorii i reguł;
- `rapidfuzz` — podobieństwo nazw podczas deduplikacji i dopasowania Google;
- `tenacity` — kontrolowane retry zapytań HTTP.

Zależności developerskie:

- `pytest`, `pytest-cov`, `respx`;
- `ruff`;
- `mypy`;
- `types-PyYAML`.

Nie dodawać `pandas`, `geopandas`, `shapely`, Selenium ani Playwrighta w MVP. Do obsługi umiarkowanej liczby kandydatów wystarczą standardowe typy Pythona i DuckDB.

## 6. Kontrakty danych

Wszystkie wymienione modele implementować jako Pydantic v2. Nazwy pól w kodzie mają być takie jak poniżej.

### 6.1 `SearchRequest`

```text
lat: float                   zakres MVP dla Polski: 48.8..55.1
lon: float                   zakres MVP dla Polski: 13.8..24.5
radius_km: float             > 0 i <= 10 dla MVP
categories: list[str]        minimum 1, aliasy z categories.yml
enrich: Literal["none", "google"]
output_path: Path
min_score: int               0..100, domyślnie 0
top: int | None              > 0, opcjonalnie ogranicza wynik końcowy
include_has_site: bool       domyślnie false
overture_release: str        domyślnie "latest"
google_max_requests: int     0..200, domyślnie 50
strict: bool                 domyślnie false
config_dir: Path | None      opcjonalny kompletny zestaw konfiguracji
overwrite: bool              domyślnie false
```

Walidacja ma kończyć się przed jakimkolwiek dostępem do sieci. MVP świadomie
odrzuca współrzędne spoza Polski zamiast udawać obsługę globalną. Argument
`--categories` rozdzielić przecinkami, usunąć białe znaki, zamienić na małe
litery, usunąć duplikaty z zachowaniem pierwszej kolejności i odrzucić puste
elementy oraz nieznane aliasy.

`output_path` musi mieć rozszerzenie `.csv`, nie może wskazywać katalogu, a po
normalizacji musi mieć niepusty stem. Ścieżki plików towarzyszących zawsze wyliczać
przez `Path.with_name`, bez ręcznej zamiany tekstu `.csv`. Symlink jako katalog
nadrzędny jest dozwolony, ale wszystkie pliki tymczasowe i finalne muszą pozostać
na tym samym filesystemie, inaczej zakończyć kodem 6 przed zapisem.

### 6.2 `SourceRef`

Pary źródło–licencja muszą pozostać razem:

```text
dataset: str
license: str | None
property_path: str | None
update_time: datetime | None
```

### 6.3 `RawOverturePlace`

```text
overture_id: str
version: int
name: str | None
lat: float
lon: float
basic_category: str | None
taxonomy_primary: str | None
taxonomy_hierarchy: list[str]
taxonomy_alternates: list[str]
confidence: float | None
operating_status: str | None
websites: list[str]
socials: list[str]
emails: list[str]
phones: list[str]
brand_name: str | None
address_freeform: str | None
locality: str | None
postcode: str | None
country: str | None
source_refs: list[SourceRef]
```

Brakujące listy zawsze normalizować do `[]`, nie pozostawiać `None`.

### 6.4 `Candidate`

Zawiera wszystkie pola potrzebne po normalizacji:

```text
raw: RawOverturePlace
distance_m: int
normalized_name: str
category_alias: str
owned_domains: list[str]
social_urls: list[str]
aggregator_urls: list[str]
other_urls: list[str]
normalized_phones: list[str]
is_chain: bool
chain_reason: str | None
bucket: CandidateBucket
score: int
score_reasons: list[str]
google_place_id: str | None
```

`GoogleMatchResult` jest dołączany tylko do obiektu wyniku sesji, nie do
serializowanego `Candidate`.

### 6.5 `CandidateBucket`

Dozwolone wartości i kolejność priorytetu:

1. `has_owned_site` — istnieje co najmniej jedna domena własna;
2. `unknown` — rekord niewiarygodny, zamknięty czasowo, niejednoznaczny lub bez nazwy;
3. `social_only` — nie ma domeny własnej, ma social media;
4. `aggregator_only` — nie ma domeny własnej ani sociali, ma tylko agregatory;
5. `likely_no_site` — brak domeny własnej, sociali i agregatorów przy wystarczających danych.

Rekord `permanently_closed` jest usuwany przed klasyfikacją i zliczany w manifeście.

### 6.6 `CalibrationReview`

Jedno pole nie wystarcza, bo lokal może być jednocześnie sieciówką i mieć własną
stronę. Plik kalibracyjny używa niezależnych enumów:

```text
entity_status: Literal["valid", "wrong_entity", "uncertain"]
target_category: Literal["yes", "no", "uncertain"]
operating_status_review: Literal["open", "closed", "uncertain"]
independence: Literal["independent", "chain", "uncertain"]
site_status: Literal["no_owned_site", "owned_site", "social_only", "uncertain"]
notes: str | None
```

Puste wszystkie pola oznaczają rekord jeszcze nieoceniony. Jeżeli choć jedno pole
oceny jest wypełnione, wszystkie pięć musi być wypełnione poprawnymi wartościami;
częściowy wiersz jest błędem walidacji.

Dla `site_status` obowiązuje priorytet: jeśli istnieje własna domena, wybrać
`owned_site` nawet gdy są też sociale; `social_only` oznacza sociale i brak własnej
domeny; `no_owned_site` oznacza brak znalezionej własnej domeny i brak sociali.

### 6.7 `GoogleMatchResult`

Model wyłącznie sesyjny:

```text
status: Literal["matched", "not_found", "ambiguous", "error", "skipped_budget"]
place_id: str | None
website_kind: Literal["owned", "social", "aggregator", "none", "unknown"]
name_similarity: float | None
address_similarity: float | None
match_distance_m: int | None
warning: str | None
```

Nie umieszczać w tym modelu ratingów ani recenzji. Surowa odpowiedź Google nie może być logowana ani zapisywana jako fixture podczas produkcyjnego uruchomienia.

## 7. Konfiguracja kategorii

`src/customer_finder/config/categories.yml` jest jedynym źródłem mapowania aliasów
użytkownika na taksonomię Overture.

Przykładowy schemat:

```yaml
version: 1
validated_against_schema: "X.Y.Z"
categories:
  cafe:
    display_name: Kawiarnia
    overture_basic: [cafe]
    overture_taxonomy: [cafe, coffee_shop, tea_room, coffee_roastery]
    score_weight: 20
  bakery:
    display_name: Piekarnia
    overture_basic: [bakery]
    overture_taxonomy: [bakery]
    score_weight: 18
  pastry:
    display_name: Cukiernia
    overture_basic: [patisserie_cake_shop]
    overture_taxonomy: [patisserie_cake_shop, chimney_cake_shop, cupcake_shop, custom_cakes_shop, donuts, pie_shop, macarons, chocolatier]
    score_weight: 25
  ice_cream:
    display_name: Lodziarnia
    overture_basic: [ice_cream_and_frozen_yoghurt]
    overture_taxonomy: [ice_cream_and_frozen_yoghurt, gelato, ice_cream_shop, frozen_yoghurt_shop]
    score_weight: 18
```

Powyższe nazwy są startowym zestawem, ale muszą zostać zatwierdzone dla wersji
schematu używanej przez aplikację. Nowa taksonomia nie jest tym samym co stare,
wycofywane pole `categories`; nie używać dawnego `overture_categories.csv` jako
źródła prawdy dla `basic_category`/`taxonomy`.

`taxonomy_snapshot.yml` nie udaje pełnej kopii globalnej taksonomii. Zawiera tylko
kody używane przez aplikację oraz dowód przeglądu:

```yaml
schema_version: "X.Y.Z"
reviewed_at: "YYYY-MM-DD"
evidence_urls:
  - "https://docs.overturemaps.org/guides/places/taxonomy/"
  - "https://docs.overturemaps.org/guides/places/taxonomy-browser/"
approved_basic: [...]
approved_taxonomy: [...]
```

Mechaniczna procedura kontroli:

1. W Milestone 1 offline sprawdzić, że każdy kod z `categories.yml` występuje w
   odpowiedniej liście snapshotu i że `validated_against_schema == schema_version`.
2. W Milestone 2 resolver STAC odczytuje `schema:version` katalogu wydania. Jeśli
   różni się od snapshotu, zatrzymać wyszukiwanie kodem 3 z instrukcją aktualizacji;
   nie próbować automatycznie tłumaczyć nazw.
3. Aktualizację snapshotu wykonywać osobnym commitem: człowiek porównuje kody z
   oficjalnym przewodnikiem i Taxonomy Browserem dla tej wersji, zapisuje datę i
   URL-e, a następnie uruchamia smoke na rzeczywistym wydaniu.
4. Mały bbox Wrocławia służy wyłącznie do sprawdzenia pokrycia. Brak rzadkiego kodu
   lokalnie jest ostrzeżeniem, nigdy dowodem, że kod nie istnieje w taksonomii.
5. Jeżeli oficjalne źródła nie pozwalają potwierdzić kodu, nie wymyślać zamiennika:
   usunąć go z configu albo zatrzymać milestone i poprosić właściciela o decyzję.
6. Każda aktualizacja snapshotu wymaga testu konfiguracji i ponownego smoke Overture.

Loader konfiguracji musi wykrywać:

- zduplikowane aliasy;
- puste listy obu mapowań;
- score poza zakresem 0..30;
- nieznane pola YAML;
- brak wersji konfiguracji.

Loader reguł domen dodatkowo odrzuca host występujący w więcej niż jednej liście,
host nieznormalizowany (wielkie litery, `www.`, końcowa kropka) i wpis niebędący
hostem. Loader denylisty odrzuca puste i zduplikowane nazwy po normalizacji.

Jeżeli jeden rekord pasuje do kilku aliasów, wybrać alias o najwyższym
`score_weight`; przy remisie wybrać alias alfabetycznie. Dodać test tej reguły.

## 8. Reguły domen

`src/customer_finder/config/domain_rules.yml` zawiera trzy listy hostów:

```yaml
social_hosts:
  - facebook.com
  - instagram.com
  - tiktok.com
  - x.com
  - linkedin.com
aggregator_hosts:
  - pyszne.pl
  - glovoapp.com
  - ubereats.com
  - tripadvisor.com
  - linktr.ee
  - google.com
ignored_hosts:
  - localhost
```

Algorytm klasyfikacji URL:

1. Dodać schemat `https://`, jeśli URL go nie ma.
2. Parsować przez `urllib.parse.urlsplit`.
3. Host zapisać małymi literami, usunąć końcową kropkę i prefiks `www.`.
4. Dopasowanie hosta ma uwzględniać subdomeny: `m.facebook.com` należy do `facebook.com`, ale `facebook.com.example.org` nie.
5. Niepoprawny URL trafia do `other_urls` i dodaje ostrzeżenie; nie może zatrzymać całego uruchomienia.
6. Host social → social; host agregatora → aggregator; poprawny pozostały publiczny host → owned.
7. Nie wykonywać HTTP GET do znalezionych domen w v1.

„Publiczny host” oznacza poprawną nazwę DNS/IDNA zawierającą co najmniej jedną
kropkę. Odrzucić adresy IP prywatne, loopback, link-local, multicast, hosty
jednoelementowe i niepoprawne IDNA. Pole arkusza zaczynające się od `=`, `+`, `-`
lub `@` nie jest dzięki temu uznawane za URL bez poprawnego hosta.

Do klasyfikatora URL przekazać łącznie wartości z Overture `websites` i `socials`;
nie ufać samej nazwie pola. Wszystkie znormalizowane listy deduplikować i sortować
leksykograficznie, aby CSV nie zależał od kolejności źródłowej.

## 9. Pobieranie Overture

### 9.1 Wybór wydania

Dla `overture_release=latest` pobrać
`https://stac.overturemaps.org/catalog.json`, odczytać główne pole `latest`,
zwalidować je wyrażeniem `^\d{4}-\d{2}-\d{2}\.\d+$` i potwierdzić istnienie
odpowiedniego linku `rel=child`. Rozwiązać względny `href` względem URL katalogu,
pobrać katalog dziecka i odczytać jego `schema:version`; zaakceptować zapis z
opcjonalnym początkowym `v`, ale przed porównaniem znormalizować do `X.Y.Z`. Brak pola jest błędem
schematu, nie `None`. Dla jawnego wydania również znaleźć jego child link, aby
poznać wersję schematu. Następnie zbudować ścieżkę
`s3://overturemaps-us-west-2/release/<release>/theme=places/type=place/*`.
Nie korzystać z dawnych `overture_releases.yaml`, `releases.json` ani
`registry-manifest.json`.

Jeśli STAC jest niedostępny:

- wykonać łącznie maksymalnie 3 próby; czekać 1 s przed drugą i 2 s przed trzecią;
- nie używać przypadkowego starego wydania;
- jeśli użytkownik podał jawne wydanie, można użyć go bez STAC;
- zakończyć kodem błędu 4 z komunikatem zawierającym etap, URL i zalecenie użycia `--overture-release`.

Jeżeli jawnie wskazane stare wydanie nie jest już dostępne, zakończyć kodem 4 i
nie przełączać się na `latest`.

Manifest musi zawierać faktycznie użyte wydanie.

### 9.2 Bounding box

Obliczyć:

```text
margin = 1.01
lat_delta = margin * radius_km / 111.32
lon_delta = margin * radius_km / (111.32 * cos(radians(lat)))
xmin = lon - lon_delta
xmax = lon + lon_delta
ymin = lat - lat_delta
ymax = lat + lat_delta
```

Jednoprocentowy margines zapobiega utracie punktów granicznych przez przybliżenie
przelicznika stopni. Dokładny haversine nadal odcina nadmiar. MVP obsługuje tylko
Polskę i promień do 10 km, więc przypadek przecięcia południka 180° jest poza
zakresem. Walidacja ma jednak odrzucać niemożliwe wyniki bbox. Test bbox musi
obejmować punkty leżące dokładnie na północnej, południowej, wschodniej i zachodniej
granicy koła i potwierdzać, że żaden nie jest pominięty.

### 9.3 Zapytanie DuckDB

Przed zapytaniem uruchomić `INSTALL httpfs` i `INSTALL spatial` tylko wtedy, gdy
rozszerzenia nie są dostępne, następnie `LOAD httpfs`, `LOAD spatial`,
`SET s3_region='us-west-2'` i `SET enable_geoparquet_conversion=true`. `spatial`
służy tylko do ekstrakcji współrzędnych punktu. Zapytanie ma wybierać tylko wymagane kolumny.
Nie używać `SELECT *`. Filtr ma wykorzystywać `bbox.xmin` i `bbox.ymin`, ponieważ
Places są punktami.

Warunek kategorii uwzględnia:

- `basic_category`;
- `taxonomy.primary`;
- przecięcie `taxonomy.hierarchy` z dozwolonymi wartościami;
- przecięcie źródłowego `taxonomy.alternates` z dozwolonymi wartościami; wewnętrzny
  model może nazywać znormalizowaną listę `taxonomy_alternates`.

Wartości parametrów przekazywać jako parametry DuckDB lub bezpiecznie tworzone literały z walidowanej konfiguracji. Nie interpolować surowych argumentów użytkownika do SQL.

Kształt zapytania (nazwy kolumn najpierw potwierdzić kontrolą schematu):

```sql
SELECT id, version, names, basic_category, taxonomy, confidence,
       operating_status, websites, socials, emails, phones, brand,
       addresses, sources, bbox,
       ST_X(geometry) AS lon, ST_Y(geometry) AS lat
FROM read_parquet(?, hive_partitioning = true)
WHERE bbox.xmin BETWEEN ? AND ?
  AND bbox.ymin BETWEEN ? AND ?
  AND (
    basic_category IN <validated_basic_values>
    OR taxonomy.primary IN <validated_taxonomy_values>
    OR list_has_any(taxonomy.hierarchy, <validated_taxonomy_values>)
    OR list_has_any(taxonomy.alternates, <validated_taxonomy_values>)
  )
ORDER BY id
```

DuckDB nie parametryzuje listy `IN` jednakowo we wszystkich wspieranych wersjach.
Dlatego helper SQL może zbudować placeholder `?,?,...` wyłącznie na podstawie
liczby elementów, a wartości przekazać osobno. Nigdy nie wstawiać do SQL samych
kodów ani ścieżki podanej przez użytkownika. Test ma zawierać alias wyglądający
jak SQL injection i potwierdzić błąd walidacji przed zapytaniem.

Przed właściwym zapytaniem wykonać kontrolę schematu wymaganych kolumn. Jeśli schemat się zmienił, błąd ma wymienić brakujące kolumny i bieżące wydanie. Nie łapać takiego błędu jako „zero wyników”.

Mapowanie pól Overture musi być jawne i przetestowane na fixture:

- `lat` i `lon` pochodzą z `ST_Y(geometry)` i `ST_X(geometry)`; bbox służy tylko
  do prefiltra i nie jest kanoniczną pozycją punktu;
- nazwa: `names.primary`, bez zgadywania alternatywy, gdy jej brak;
- adres: pierwszy wpis z `addresses`, preferując `country == "PL"`; przy remisie
  zachować kolejność źródłową;
- `brand_name = brand.names.primary`; źródłowe `brand` jest pojedynczym obiektem,
  brak marki → `None`;
- kategoria pochodzi wyłącznie z `basic_category`, `taxonomy.primary`,
  `taxonomy.hierarchy` i źródłowego `taxonomy.alternates`; nie zależy od
  wycofywanego pola `categories`;
- źródła mapować do `SourceRef` bez rozdzielania datasetu od licencji; zachować
  `property_path` i `update_time`, jeżeli występują;
- każdą brakującą listę zamienić na `[]`, ale nie maskować braku wymaganej kolumny.

Licznik po SQL nosi nazwę `raw_category_bbox`, ponieważ SQL już filtruje
kategorie. Niefiltrowane `COUNT(*)` w bbox wykonywać tylko diagnostycznie, gdy
`raw_category_bbox == 0`; nie pobierać pełnych rekordów diagnostycznych.

### 9.4 Dokładny promień

Po pobraniu bbox obliczyć haversine dla każdego rekordu. Zostawić tylko `distance_m <= radius_km * 1000`. Wynik zaokrąglić do pełnych metrów.

Testy geometryczne muszą zawierać:

- ten sam punkt → 0 m;
- dwa znane punkty we Wrocławiu z tolerancją 1%;
- punkt dokładnie na granicy promienia;
- niepoprawne latitude/longitude.

## 10. Normalizacja i deduplikacja

### 10.1 Nazwa

`normalized_name`:

- Unicode NFKC;
- małe litery;
- zamiana znaków interpunkcyjnych na spacje;
- redukcja wielokrotnych spacji;
- nie usuwać polskich znaków;
- nie usuwać słów typu `kawiarnia` i `cukiernia`, ponieważ mogą należeć do nazwy.

### 10.2 Telefon

W v1 normalizacja telefonu:

- zachować początkowe `+`;
- usunąć spacje, myślniki i nawiasy;
- polskie 9 cyfr bez prefiksu zamienić na `+48...` tylko gdy `country == PL`;
- wartości niejednoznaczne zachować jako surowe, ale nie używać do deduplikacji.

### 10.3 Deduplikacja

Przed porównywaniem posortować rekordy po `overture_id`. Zbudować nieskierowany
graf: rekord jest wierzchołkiem, a każda spełniona reguła 1–3 tworzy krawędź.
Duplikatami są całe spójne składowe grafu, a nie wynik zależny od kolejności pętli.

Kolejność reguł:

1. Identyczne `overture_id` → ten sam rekord.
2. Ten sam znormalizowany telefon i odległość <= 100 m → duplikat.
3. Podobieństwo nazwy RapidFuzz >= 92 oraz odległość <= 50 m → duplikat.
4. W pozostałych przypadkach zachować oba rekordy.

Przy łączeniu każdej składowej:

- rekord z najwyższym `confidence` jest bazą (`None` traktować jako `-1`); przy
  remisie wygrywa alfabetycznie najmniejszy `overture_id`;
- listy URL, telefonów, e-maili i źródeł są sumowane bez duplikatów;
- nie nadpisywać niepustego adresu pustym;
- w manifeście zwiększyć `deduplicated_count`;
- zapisać w logu tylko identyfikatory Overture, bez pełnych danych kontaktowych.

Test ma uruchomić te same rekordy w co najmniej trzech różnych kolejnościach i
otrzymać identyczny wynik. `deduplicated_count = liczba rekordów wejściowych minus
liczba składowych wyjściowych`.

## 11. Sieciówki

`src/customer_finder/config/chain_denylist.yml` zawiera jawne nazwy dużych sieci. Porównanie odbywa się po znormalizowanej nazwie marki i nazwy miejsca.

`is_chain = true`, jeśli spełniony jest co najmniej jeden warunek:

- marka lub nazwa znajduje się na denyliście;
- w wyniku wyszukiwania istnieją co najmniej 3 rekordy o tej samej znormalizowanej marce;
- istnieją co najmniej 3 rekordy o nazwie podobnej >= 95 i różnych lokalizacjach.

Sieciówka nie jest domyślnie usuwana przed scoringiem. Otrzymuje karę. Rekordy z denylisty mogą być wykluczone z końcowego CSV, jeśli wynik po karze spadnie poniżej `min_score`.

## 12. Klasyfikacja i scoring

### 12.1 Kolejność klasyfikacji

1. `operating_status == permanently_closed` → wykluczyć.
2. Co najmniej jedna `owned_domain` → `has_owned_site`.
3. Brak nazwy albo `confidence < 0.30` → `unknown`.
4. `operating_status == temporarily_closed` → `unknown`.
5. Są sociale → `social_only`.
6. Są tylko agregatory → `aggregator_only`.
7. Brak domen/sociali/agregatorów, ale `other_urls` nie jest puste → `unknown`;
   niepoprawny lub ignorowany URL nie jest dowodem braku strony.
8. Wszystkie cztery listy URL są puste i jest nazwa oraz co najmniej adres albo
   telefon → `likely_no_site`.
9. Inaczej → `unknown`.

`has_owned_site` nie trafia domyślnie do CSV. Flaga `--include-has-site` pozwala go dołączyć do diagnostyki.

### 12.2 Wzór scoringu

Punktacja jest jawna i deterministyczna:

```text
start                                      10
waga kategorii z categories.yml            +0..30
bucket likely_no_site                      +30
bucket social_only                         +22
bucket aggregator_only                     +16
bucket unknown                              -15
telefon                                    +8
email                                      +4
adres i locality                           +5
confidence >= 0.80                         +10
confidence >= 0.50 i < 0.80                 +5
confidence < 0.30                          -15
operating_status open                       +5
brand istnieje                              -5
is_chain                                   -30
brak nazwy                                 -40
```

Wynik obciąć do zakresu 0..100. Każda zmiana wyniku dopisuje czytelny kod do `score_reasons`, np. `category:pastry:+25`, `social_only:+22`, `chain:-30`.

Nie modyfikować score na podstawie ocen Google.

## 13. Google Places enrichment

Ten moduł powstaje dopiero po ukończeniu i ręcznej kalibracji pipeline’u Overture.

### 13.1 Konfiguracja

Klucz jest pobierany wyłącznie z `GOOGLE_MAPS_API_KEY`. `.env.example` zawiera nazwę zmiennej z pustą wartością. `.env` znajduje się w `.gitignore`.

Przed pierwszym zapytaniem:

- sprawdzić obecność klucza;
- sprawdzić `google_max_requests > 0`;
- policzyć kandydatów przeznaczonych do enrichment;
- jeśli kandydatów jest więcej niż budżet, wybrać najwyższy score i pozostałym nadać sesyjny status `skipped_budget`;
- budżet oznacza wszystkie fizyczne próby HTTP, włącznie z retry, a nie liczbę
  kandydatów. Współdzielony licznik prób musi być zwiększany atomowo przed wysłaniem
  requestu; po osiągnięciu limitu żadna współbieżna praca nie może wysłać kolejnego.

`google_max_requests` jest bezpiecznikiem liczby żądań, nie gwarancją konkretnej
kwoty. `websiteUri` może wpływać na SKU i koszt zgodnie z aktualnym cennikiem;
README ma o tym ostrzegać i linkować oficjalny kalkulator/cennik.

### 13.2 Żądanie

Użyć `POST https://places.googleapis.com/v1/places:searchText`.

Zapytanie tekstowe:

```text
{name}, {address_freeform}, {locality}
```

Body zawiera `textQuery`, `languageCode="pl"`, `regionCode="PL"`, `pageSize=3`
oraz `locationBias.circle` ze środkiem w punkcie kandydata i promieniem 250 m.
Nie dodawać nazwy kraju do tekstu, bo jawna lokalizacja w zapytaniu może osłabić
bias. Nagłówki to `Content-Type: application/json`, `X-Goog-Api-Key` i
`X-Goog-FieldMask`; maska jest jednym ciągiem bez spacji:

```text
places.id,
places.displayName,
places.formattedAddress,
places.websiteUri,
places.location
```

Nie wykonywać osobnego Place Details, jeśli Text Search zwrócił te pola.

### 13.3 Dopasowanie encji

Google nie może automatycznie nadpisać kandydata tylko dlatego, że zwrócił pierwszy wynik.

Obliczyć:

- `name_similarity` przez RapidFuzz po identycznej normalizacji nazwy;
- `address_similarity` jako Jaccard znormalizowanych tokenów ulicy, locality i
  kodu pocztowego, po usunięciu przecinków i różnic wielkości liter;
- odległość haversine między współrzędnymi Overture i `places.location`;
- numer budynku wyodrębniony prostą regułą tokenową; jeśli obie strony mają numer
  i numery się różnią, wynik odrzucić. Nie próbować rozumieć złożonych lokali.

Za `matched` uznać wynik tylko, gdy:

- `name_similarity >= 88`;
- `address_similarity >= 50`;
- odległość `<= 250 m`;
- numery budynków nie są sprzeczne;
- dokładnie jeden wynik spełnia wszystkie powyższe warunki.

Po odrzuceniu surowych wyników niespełniających progów: zero kwalifikujących się
wyników → `not_found`, dokładnie jeden → `matched`, więcej niż jeden →
`ambiguous`. Sama liczba surowych elementów `places` nie wyznacza statusu. Błąd
API → `error`. Nie zgadywać.

`website_kind` obliczyć w pamięci regułami z sekcji 8 na pojedynczym
`websiteUri`: poprawny publiczny host spoza list → `owned`, social → `social`,
agregator → `aggregator`, brak pola/pusta wartość → `none`, niepoprawna lub
ignorowana wartość → `unknown`. Nie wykonywać żądania do URL.

### 13.4 Retry i limity

- 429 i 5xx: łącznie maksymalnie 3 próby, exponential backoff z jitterem;
- 401/403: bez retry, zatrzymać nowe requesty; błąd konfiguracji, kod 3;
- 400: bez retry, zatrzymać nowe requesty; błąd kontraktu/implementacji, kod 3;
- timeout connect 5 s, read 15 s;
- maksymalna współbieżność 3;
- osobno liczyć `logical_candidates` i `http_attempts`; budżet dotyczy `http_attempts`;
- nigdy nie przekraczać `google_max_requests`.

401, 403 i 400 są błędami fatalnymi niezależnie od `strict`, bo oznaczają błędny
klucz/uprawnienia albo kontrakt requestu. `strict` dotyczy wyłącznie timeoutów,
429 i 5xx poszczególnych kandydatów. Jeśli taka część enrichment zakończy się błędem:

- `strict=false`: utworzyć wynik Overture, dodać ostrzeżenie i statusy sesyjne;
- `strict=true`: nie publikować finalnego CSV i zakończyć kodem 5.

### 13.5 Przechowywanie

Domyślny tryb produkcyjny:

- można zapisać `google_place_id`;
- nie zapisywać surowej nazwy, adresu, `websiteUri`, `googleMapsUri`, ratingów ani odpowiedzi JSON;
- wynik Google **nie zmienia** trwałego `bucket`, `score` ani pól kalibracji;
- w CSV może zmienić się wyłącznie `google_place_id` dla jednoznacznego matchu;
- CLI pokazuje tylko agregaty operacyjne (`matched`, `ambiguous`, `not_found`,
  `errors`, `skipped_budget`). Nie wyświetla ani nie zapisuje per-rekordowego
  `website_kind`, podobieństw, nazwy, adresu ani URL Google;
- oceny kalibracyjne pochodzą od użytkownika, nie z automatycznego kopiowania
  danych Google, i istnieją wyłącznie w osobnym `calibration.csv`; ponowne
  wyszukiwanie ich nie importuje.

To jest świadoma decyzja v1: trwały efekt Google na pojedynczym rekordzie to tylko
dozwolony do przechowania Place ID i precyzyjniejszy link ręcznej weryfikacji.
`website_kind` istnieje w pamięci wyłącznie do agregatów bieżącego procesu. Jeśli
w przyszłości powstanie UI pokazujące dane Google, będzie osobnym milestone’em po
ponownej kontroli Places Policies, warunków EEA i wymagań atrybucji. Nie dodawać
raportu HTML/CSV jako „ułatwienia”.

Wynik sesyjny istnieje wyłącznie po to, by wskazać rekordy do ręcznej kontroli.
`place_id` starszy niż 12 miesięcy traktować jako wymagający odświeżenia przed
użyciem. Pipeline nie scala jeszcze werdyktów pomiędzy kolejnymi wyszukiwaniami;
do kalibracji służy osobny, jawny przepływ z sekcji 15.4.

Jeśli właściciel projektu chce trwale zapisywać dodatkowe pola Google, musi najpierw jawnie zmienić tę decyzję po sprawdzeniu aktualnych warunków korzystania. Agent nie może sam rozszerzyć retencji.

## 14. Linki do ręcznej weryfikacji

Dla każdego wyniku końcowego wygenerować URL:

```text
https://www.google.com/maps/search/?api=1&query=<urlencoded name address locality>
```

Jeżeli istnieje `google_place_id`, dodać `&query_place_id=<urlencoded place_id>`;
parametr `query` nadal jest wymagany jako tekst awaryjny. URL budować przez
`urllib.parse.urlencode`, nie przez ręczne sklejanie.

`<stem>.verify_links.txt` zawiera maksymalnie `top` albo domyślnie 30 linków, w kolejności malejącego score. Format każdej sekcji:

```text
[01] Nazwa — bucket=likely_no_site — score=83
https://...
```

Nie pobierać zawartości tych URL-i.

## 15. CSV i manifest

### 15.1 Kolumny CSV

Kolejność jest częścią kontraktu:

```text
overture_id
overture_release
name
category
bucket
score
score_reasons
address
locality
postcode
country
lat
lon
distance_m
phones
emails
socials
aggregators
owned_domains
brand_name
is_chain
chain_reason
confidence
operating_status
google_place_id
source_refs
```

Jedyną kolumną źródeł jest `source_refs`, zakodowana
jako tablica obiektów JSON, dzięki czemu dataset i licencja nie tracą powiązania.

Listy kodować w jednej komórce jako JSON, nie jako tekst rozdzielany przecinkami. CSV zapisywać w UTF-8 z BOM (`utf-8-sig`), aby polski Excel poprawnie otwierał znaki.

Przed zapisem każdej skalarnej komórki tekstowej chronić arkusze przed formula
injection: jeżeli po usunięciu początkowych białych znaków wartość zaczyna się od
`=`, `+`, `-` albo `@`, poprzedzić całą komórkę apostrofem. Nie modyfikować
elementów wewnątrz JSON; komórka JSON zaczyna się od `[` lub `{` i sama nie jest
formułą. Dodać test dla wszystkich czterech prefiksów i round-trip JSON.

Sortowanie:

1. score malejąco;
2. distance_m rosnąco;
3. name rosnąco.

### 15.2 Manifest

Plik `<stem>.manifest.json` (dla `leads.csv`: `leads.manifest.json`):

```text
schema_version
run_id UUID
started_at UTC
finished_at UTC
duration_seconds
command_parameters bez sekretów
overture_release
counts: raw_category_bbox, inside_radius, permanently_closed,
        deduplicated, has_owned_site, social_only, aggregator_only,
        likely_no_site, unknown, output
google: enabled, request_budget, logical_candidates, http_attempts, matched, ambiguous,
        not_found, errors, skipped_budget
warnings
tool_version
python_version
duckdb_version
data_fresh_until UTC
```

Manifest powstaje także przy błędzie jako `<stem>.failed.manifest.json`, ale nie
może zawierać sekretów ani surowych odpowiedzi API. Nie jest częścią zestawu
sukcesu i nigdy nie ma markera `.complete`.

### 15.3 Atomowość zestawu plików i retencja

Dla `--output out/leads.csv` nazwy są dokładnie:

```text
out/leads.csv
out/leads.manifest.json
out/leads.verify_links.txt
out/leads.complete
```

Utworzyć katalog nadrzędny, jeśli nie istnieje. Jeżeli istnieje którykolwiek z
powyższych finalnych plików, bez `--overwrite` zakończyć kodem 6 przed siecią.
Z `--overwrite` wolno nadpisać wyłącznie dokładnie ten zestaw plików dla podanego
stemu, nigdy cały katalog.

Wszystkie pliki najpierw zapisać w katalogu obok wyniku o nazwie
`.leads.tmp-<run_uuid>` i zamknąć deskryptory. Bez `--overwrite` promować je przez
atomowe rename w obrębie tego samego filesystemu, a `leads.complete` (zawiera
`run_id` i SHA-256 każdego pozostałego pliku zestawu) promować jako ostatni. Z `--overwrite` najpierw
przenieść dokładny stary zestaw do `.leads.backup-<run_uuid>`, promować nowy i
usunąć backup dopiero po weryfikacji markerów/hashów. Jeśli promocja zawiedzie,
usunąć tylko części nowego `run_id` i przywrócić cały backup. Tylko zestaw z
poprawnym markerem `.complete` jest sukcesem. Przy błędzie nie usuwać innych
wyników użytkownika. Test ma symulować awarię po każdym rename i potwierdzić brak
mieszanego zestawu oraz poprawny rollback.

`data_fresh_until = finished_at + 30 dni`. To celowo mniej niż maksymalnie
60-dniowa publiczna retencja wydań deklarowana obecnie przez Overture. Przy odczycie starszego wyniku CLI ma
ostrzec, ale nie usuwać danych automatycznie. README opisuje ręczne usuwanie
starych zestawów oraz ponowne uruchomienie na aktualnym wydaniu. Nie zakładać, że
dowolnie stare wydania Overture pozostaną dostępne.

### 15.4 Ręczna kalibracja — kontrakt, nie luźna notatka

Komendy:

```text
finder calibration prepare --leads out/leads.csv --output out/calibration.csv --limit 30
finder calibration evaluate --file out/calibration.csv --output out/calibration.summary.json
```

`prepare` tworzy kolumny
`rank,overture_id,name,google_maps_url,entity_status,target_category,operating_status_review,independence,site_status,notes`
i kopiuje top N bez nadpisywania pliku. Człowiek otwiera linki i wypełnia pięć
enumów z sekcji 6.6. Agent nie może sam wypełnić ocen ani uznać braku odpowiedzi
za `no_owned_site`.

`evaluate` odrzuca duplikaty ID, nieznane wartości i luki w rankingu. Do samego
raportu wymaga minimum 20 kompletnie ocenionych wierszy. Do `passed=true` wymaga,
aby kompletne były wszystkie wiersze wygenerowane przez `prepare` (domyślnie 30).
Liczy osobno top 20 oraz cały kompletnie oceniony plik:

```text
reviewed = liczba kompletnie ocenionych wierszy
target_independent = count(entity_status=valid AND target_category=yes
                           AND operating_status_review=open
                           AND independence=independent)
target_precision = target_independent / reviewed
target_without_owned_site = count(warunki target_independent
                                  AND site_status IN [no_owned_site, social_only])
no_site_precision = target_without_owned_site / reviewed
chain_ratio = count(independence=chain) / reviewed
wrong_ratio = count(entity_status=wrong_entity OR target_category=no) / reviewed
```

`closed` i wszystkie `uncertain` pozostają w mianowniku, aby nie zawyżać jakości. Podsumowanie
JSON zawiera liczniki, wzory, progi, `passed` i SHA-256 ocenianego CSV. Jeżeli
progi Milestone 5 są spełnione, dodatkowo powstaje
`<stem>.approved.json` (domyślnie `out/calibration.approved.json`) z hashami CSV i
summary. Tylko ten artefakt odblokowuje
Milestone 6; zmiana CSV unieważnia zgodność hasha.

### 15.5 Kalibracja dopasowania Google

Po smoke Google uruchomić:

```text
finder google-calibration prepare --leads out/leads.csv --output out/google-match-review.csv --limit 10
finder google-calibration evaluate --file out/google-match-review.csv --output out/google-match-review.summary.json
```

`prepare` wybiera pierwsze 10 rekordów z niepustym `google_place_id` i tworzy
`rank,overture_id,name,google_maps_url,google_place_id,same_entity,notes`, gdzie
`same_entity` przyjmuje `yes`, `no` albo `uncertain`. Człowiek otwiera link i
ocenia tożsamość; agent nie wypełnia pola. `evaluate` wymaga 10 pełnych ocen,
odrzuca duplikaty oraz `uncertain` jako niespełniające bramki i liczy
`entity_match_precision = yes / reviewed`. Przy wartości `1.0` tworzy
`<stem>.approved.json` (domyślnie `google-match-review.approved.json`) z SHA-256
CSV i summary. Zmiana któregokolwiek
pliku unieważnia approval. Jeżeli jest mniej niż 10 jednoznacznych matchów, bramka
nie przechodzi; nie uzupełniać próbki rekordami `ambiguous` ani duplikatami.

## 16. CLI i kody wyjścia

Komenda główna:

```text
finder search [OPTIONS]
```

Dodatkowe komendy diagnostyczne:

```text
finder config validate
finder overture schema --release latest
finder calibration prepare [OPTIONS]
finder calibration evaluate [OPTIONS]
finder google-calibration prepare [OPTIONS]
finder google-calibration evaluate [OPTIONS]
finder version
```

Kody wyjścia:

- `0` — sukces, także pusty wynik i sukces częściowy Google przy `strict=false`;
- `1` — nieoczekiwany błąd programu; wypisać `run_id`, bez stack trace domyślnie;
- `2` — niepoprawne argumenty;
- `3` — błędna konfiguracja, YAML lub brak klucza;
- `4` — błąd Overture/STAC/DuckDB;
- `5` — wymagany Google enrichment nie zakończył się poprawnie w `strict=true`;
- `6` — błąd zapisu wyniku.

CLI ma wypisać krótkie podsumowanie, a pełne szczegóły umieścić w manifeście. Nigdy nie wypisywać klucza API.

Pusty wynik jest poprawnym zestawem: CSV zawiera sam nagłówek, manifest liczniki
zerowe, `<stem>.verify_links.txt` jest pusty, marker `.complete` istnieje, a CLI wypisuje
ostrzeżenie. Wyjątkiem jest opisany w sekcji 22 przypadek, gdy bbox ma rekordy,
ale filtr kategorii daje zero — wtedy nadal kod 0, lecz ostrzeżenie musi wskazać
prawdopodobną niezgodność taksonomii.

## 17. Pipeline

`pipeline.py` ma być jedynym modułem orkiestrującym. Kolejność:

1. Walidacja `SearchRequest`.
2. Wczytanie i walidacja YAML.
3. Preflight outputu: wyznaczenie całego zestawu ścieżek, kontrola kolizji,
   `--overwrite`, prawa zapisu i zgodność filesystemu. Ten krok musi skończyć się
   przed pierwszym dostępem do sieci.
4. Utworzenie `run_id` i ścieżki failed manifestu.
5. Rozwiązanie wydania Overture.
6. Obliczenie bbox.
7. Kontrola schematu.
8. Zapytanie bbox i kategorii.
9. Mapowanie wyników na `RawOverturePlace`.
10. Dokładny filtr haversine.
11. Usunięcie `permanently_closed`.
12. Normalizacja.
13. Deduplikacja.
14. Rozpoznanie sieciówek.
15. Klasyfikacja.
16. Scoring.
17. Usunięcie `has_owned_site`, chyba że flaga pozwala.
18. Filtr `min_score`.
19. Sortowanie i opcjonalne `top`.
20. Opcjonalny Google enrichment tylko dla bieżącej listy; nie przelicza bucketu
    ani score, tworzy jedynie wynik sesyjny i opcjonalny `google_place_id`.
21. Wygenerowanie linków weryfikacyjnych.
22. Atomowy zapis całego zestawu oraz markera `.complete`.
23. Podsumowanie CLI.

Każdy etap zwraca wynik i statystyki. Nie używać globalnego stanu.

## 18. Logowanie i bezpieczeństwo

- domyślny poziom `INFO`, `--verbose` włącza `DEBUG`;
- logi na stderr, dane wynikowe do plików;
- nie logować e-maili, telefonów, pełnych odpowiedzi API ani sekretów;
- przy debug można logować `overture_id`, etap i licznik;
- wszystkie żądania HTTP mają jawny timeout;
- User-Agent ma zawierać nazwę aplikacji i wersję;
- `.env`, `out/*`, pliki tymczasowe i cache nie mogą trafić do Git;
- błędy nie mogą zawierać nagłówków autoryzacyjnych.

## 19. Testy

### 19.1 Unit

Minimalny zestaw:

- `geometry`: bbox i haversine;
- `normalize`: polskie nazwy, telefony, URL i subdomeny;
- `classify`: każdy bucket i priorytet reguł;
- `scoring`: dokładne oczekiwane wartości i clamp 0..100;
- `deduplicate`: ID, telefon, nazwa+odległość oraz przypadki niededuplikowane;
- `chain detection`: denylista i trzy placówki;
- `config`: poprawny i błędny YAML;
- `Google matching`: matched, ambiguous, not_found;
- `output`: kolejność kolumn, JSON w komórkach, ochrona przed formułami, UTF-8 BOM,
  odmowa nadpisania i poprawny marker kompletności.

### 19.2 Integration bez sieci

Fixture Parquet zawiera co najmniej 24 rekordy, w tym:

- 2 kawiarnie będące duplikatami;
- 1 lokal z domeną własną;
- 1 social-only;
- 1 aggregator-only;
- 1 likely-no-site;
- 1 brak nazwy;
- 1 niski confidence;
- 1 permanently closed;
- 1 sieciówkę z denylisty;
- 1 punkt poza bbox;
- 1 punkt w bbox, ale poza okręgiem.

Pozostałe rekordy mają zapewnić co najmniej 20 wierszy do deterministycznej
kalibracji fixture, kilka remisów score oraz spójną składową deduplikacji długości
3. Fixture nie może pochodzić z produkcyjnej odpowiedzi Google.

Test pełnego pipeline’u porównuje CSV z `expected_leads.csv` i sprawdza wszystkie liczniki manifestu.

Google API mockować przez `respx`; sprawdzić retry, budżet, timeout i brak klucza.

### 19.3 Smoke z siecią

Smoke testy nie działają domyślnie w zwykłym CI. Offline unit i integration są
obowiązkowe zawsze. Smoke Overture jest obowiązkowy ręcznie przed Milestone 5 i
release; smoke Google przed ukończeniem Milestone 6. Włączenie:

```powershell
$env:RUN_NETWORK_TESTS='1'
pytest -m network
```

Smoke Overture: promień 0.5 km i jedna kategoria, maksymalnie 20 wyświetlonych rekordów. Test Google wymaga osobnej flagi i limitu 1 zapytania.

### 19.4 Bramka jakości

Przed każdym milestone:

```powershell
ruff format --check .
ruff check .
mypy src
pytest -q --cov=customer_finder --cov-report=term-missing
```

Minimalne pokrycie: 85% dla całego pakietu. Nie wyłączać testów lub reguł lintera tylko po to, aby bramka przeszła. Każde wyłączenie wymaga komentarza z powodem.

## 20. Docker

Dockerfile wieloetapowy nie jest wymagany. Ważniejsza jest przewidywalność:

- obraz bazowy `python:3.12-slim`;
- użytkownik nie-root;
- instalacja pakietu z `pyproject.toml`;
- rozszerzenia DuckDB `httpfs` i `spatial` przygotowane podczas budowania albo jawnie sprawdzane przy starcie;
- `/app/out` jako zapisywalny katalog;
- `ENTRYPOINT ["finder"]`.

Przykład:

```powershell
docker build -t customer-finder .
docker run --rm `
  -v "${PWD}/out:/app/out" `
  customer-finder search `
  --lat 51.1079 --lon 17.0385 --radius-km 3 `
  --categories cafe,bakery,pastry,ice_cream `
  --output /app/out/leads.csv
```

Dla Google przekazać sekret przez `--env-file .env`, nie przez argument widoczny w historii poleceń.

## 21. Etapy implementacji i bramki

Agent ma realizować etapy sekwencyjnie. Po każdym etapie zaktualizować checklistę w opisie commita lub raporcie pracy.

### Milestone 0 — szkielet

Zadania:

1. Zainicjalizować strukturę plików.
2. Utworzyć `pyproject.toml`, `.gitignore`, `.env.example`.
3. Dodać minimalne `finder version`.
4. Dodać konfigurację Ruff, mypy i pytest.
5. Utworzyć test uruchomienia CLI.

Bramka:

- `pip install -e ".[dev]"` działa;
- `finder version` zwraca kod 0;
- wszystkie cztery komendy jakości przechodzą.

Nie przechodzić dalej, jeśli pakiet nie instaluje się w czystym virtualenv.

### Milestone 1 — modele i konfiguracja

Zadania:

1. Modele Pydantic.
2. YAML kategorii, domen i denylisty.
3. `finder config validate`.
4. Wyłącznie offline: zgodność `categories.yml` z dostarczonym
   `taxonomy_snapshot.yml` według punktu 1 sekcji 7. Nie uruchamiać STAC/DuckDB.
5. Testy błędnych zakresów i YAML.

Bramka: pełny zestaw unit testów konfiguracji i modeli przechodzi; CLI wskazuje dokładną ścieżkę błędnego pliku i pole.

### Milestone 2 — geometria i Overture

Zadania:

1. Bbox i haversine.
2. Resolver STAC/wydania.
3. Kontrola schematu.
4. Zapytanie DuckDB.
5. Mapowanie zagnieżdżonych pól.
6. Fixture Parquet i integracja bez sieci.
7. Live: porównanie `schema:version` STAC ze snapshotem oraz smoke pokrycia
   kategorii według punktów 2–6 sekcji 7.

Bramka:

- test dokładnego promienia przechodzi;
- zmiana lub brak kolumny daje jawny błąd, a nie pusty wynik;
- jeden ręczny smoke Overture działa;
- wynik zapytania dla fixture jest deterministyczny.

### Milestone 3 — jakość kandydatów

Zadania:

1. Normalizacja.
2. Deduplikacja.
3. Reguły sieciówek.
4. Buckety.
5. Scoring z reasons.

Bramka: wszystkie przypadki z sekcji testów mają jawne asercje; ręczny przegląd 20 rekordów z fixture nie wykazuje sprzeczności bucketów.

### Milestone 4 — output i kompletne CLI

Zadania:

1. Orkiestracja pipeline.
2. CSV, manifest, atomowy zapis.
3. `<stem>.verify_links.txt`.
4. Kody wyjścia.
5. README z jedną komendą lokalną i Docker.

Bramka:

- test end-to-end bez sieci porównuje dokładny CSV;
- symulowany błąd zapisu nie pozostawia finalnego pliku;
- manifest zgadza się z liczbą rekordów;
- sekret testowy nigdy nie występuje w logach.

### Milestone 5 — kalibracja na Nadodrzu/Wrocławiu

Zadania wykonywane przez człowieka lub agenta pod nadzorem:

1. Uruchomić promień 3 km dla czterech kategorii.
2. Zapisać manifest i czas.
3. Otworzyć ręcznie top 30 linków.
4. Dla każdego wypełnić pięć niezależnych pól `CalibrationReview` z sekcji 6.6.
5. Uruchomić `finder calibration evaluate` i zachować summary oraz approval.
6. Policzyć mechanicznie metryki top 20 i top 30; nie liczyć ich ręcznie.
7. Zmienić tylko progi/konfigurację, nie dodawać wyjątków w kodzie dla pojedynczych firm.

Bramka:

- co najmniej 80% top 20 to działające, niezależne lokale z docelowych kategorii;
- co najmniej 70% top 20 nie ma własnej domeny według ręcznej kontroli;
- przebieg bez Google trwa <= 5 min na typowym łączu, poza pierwszym pobraniem rozszerzeń/cache;
- wszystkie błędne klasyfikacje są opisane przed zmianą reguł.
- `out/calibration.approved.json` istnieje i jego hash odpowiada ocenionemu CSV.

Jeśli bramka nie przechodzi, nie implementować Google. Najpierw poprawić Overture, mapowanie kategorii, deduplikację lub scoring.

### Milestone 6 — Google enrichment

Warunek wejścia: istnieje poprawny `calibration.approved.json`, a jego SHA-256
zgadza się z bieżącym `calibration.csv`. W przeciwnym razie agent zatrzymuje ten
milestone i wraca do Milestone 5.

Zadania:

1. Klient Text Search (New).
2. Budżet i retry.
3. Dopasowanie encji.
4. Sesyjna klasyfikacja website kind.
5. Przechowywanie wyłącznie dozwolonych pól zgodnie z sekcją 13.5.
6. Mockowane testy i pojedynczy smoke.

Bramka:

- jedno zapytanie na kandydata, bez Details;
- nigdy nie przekracza budżetu;
- ambiguous nie jest uznawane za match;
- brak klucza kończy się kodem 3;
- 10 ręcznie sprawdzonych dopasowań ma 100% poprawności encji; jeśli nie, podnieść progi, nie zgadywać;
- `google-match-review.approved.json` istnieje i ma hash zgodny z plikiem 10 ocen;
- surowe odpowiedzi Google nie pojawiają się w `out/`, logach ani manifeście.
- Google nie zmienia trwałego bucketu ani score; nie powstaje raport zawierający
  per-rekordowe pola Google inne niż Place ID w CSV.

### Milestone 7 — finalna dokumentacja i release v0.1.0

Zadania:

1. Pełny README: instalacja, Docker, komendy, koszt Google, interpretacja bucketów, ograniczenia.
2. `CHANGELOG.md`.
3. Licencje i atrybucje źródeł.
4. Test instalacji w nowym katalogu/virtualenv.
5. Tag dopiero po przejściu wszystkich bramek.

## 22. Procedury diagnostyczne

### Problem: Overture zwraca zero wyników

Nie zmieniać od razu kategorii. Wykonać kolejno:

1. Potwierdzić lat/lon i bbox w manifeście.
2. Uruchomić diagnostyczne `COUNT(*)` w bbox bez filtra kategorii.
3. Jeśli count=0, sprawdzić ścieżkę wydania i pushdown bbox.
4. Jeśli count>0, pobrać rozkład `basic_category` i `taxonomy.primary` dla maksymalnie 100 rekordów.
5. Porównać z YAML i oficjalną taksonomią.
6. Dopiero potem poprawić config.

Program nie może zwrócić sukcesu bez ostrzeżenia, jeśli surowy bbox ma wyniki, a filtr kategorii daje zero.

### Problem: za dużo wyników spoza promienia

1. Sprawdzić kolejność lat/lon.
2. Sprawdzić metry haversine na dwóch rekordach.
3. Upewnić się, że bbox jest tylko prefiltracją.
4. Dodać test regresyjny punktu w bbox, ale poza kołem.

### Problem: duplikaty

1. Wypisać tylko ID, znormalizowaną nazwę, odległość między rekordami i regułę deduplikacji.
2. Nie zwiększać progu odległości globalnie bez zestawu kontrprzykładów.
3. Dodać fixture dla false positive i false negative.

### Problem: małe lokale znikają

1. Sprawdzić, czy usunął je SQL, status, deduplikacja, bucket czy min_score.
2. Nie obniżać globalnie progu confidence przed poznaniem etapu utraty.
3. Niski confidence powinien prowadzić do `unknown`, nie do cichego usunięcia.

### Problem: błędny match Google

1. Natychmiast oznaczyć jako `ambiguous`.
2. Dodać zanonimizowany fixture struktury odpowiedzi.
3. Sprawdzić normalizację nazwy i adresu.
4. Podnieść progi albo wymagać ręcznej kontroli.
5. Nigdy nie wybierać „najbliższego” słabego wyniku tylko po to, aby uniknąć `unknown`.

### Problem: 429 lub koszty Google

1. Przerwać dalsze nowe zapytania po osiągnięciu budżetu.
2. Retry tylko według reguł.
3. Zapisać licznik i ostrzeżenie w manifeście.
4. Nie przełączać automatycznie na Playwright.

### Problem: DuckDB nie może pobrać rozszerzenia

1. Sprawdzić, czy Docker przygotował wymagane rozszerzenie podczas builda.
2. Sprawdzić połączenie HTTPS i certyfikaty.
3. Nie wyłączać weryfikacji TLS.
4. Zwrócić jawny błąd środowiska z instrukcją odbudowania obrazu.

## 23. Zasady pracy autonomicznego agenta

Agent wykonujący ten dokument ma przestrzegać poniższej pętli przy każdym zadaniu:

1. Przeczytaj cały bieżący milestone i związane kontrakty.
2. Sprawdź stan repozytorium i istniejące zmiany użytkownika.
3. Wprowadź najmniejszy kompletny fragment.
4. Uruchom testy dotyczące fragmentu.
5. Uruchom pełną bramkę jakości.
6. Przeczytaj diff i usuń przypadkowe zmiany.
7. Sprawdź, czy logi i fixtures nie zawierają sekretów ani danych pobranych z produkcyjnego Google.
8. Dopiero wtedy oznacz krok jako ukończony.

Jeśli test nie przechodzi:

- najpierw ustalić pierwszą przyczynę, nie poprawiać wielu modułów naraz;
- nie usuwać asercji;
- nie mockować kodu, który powinien być testowany;
- dodać test regresyjny dla znalezionego błędu;
- po poprawce ponownie uruchomić test lokalny i pełną bramkę.

Jeśli dokument i pomysł implementacyjny agenta są sprzeczne, wygrywa dokument. Jeśli dokument jest technicznie niemożliwy z powodu zmiany zewnętrznego API, agent ma zatrzymać dany milestone, zebrać dowody z oficjalnej dokumentacji i opisać minimalną zmianę kontraktu. Nie może samodzielnie przeprojektować systemu.

## 24. Definition of Done v1

MVP jest ukończone tylko wtedy, gdy wszystkie punkty są prawdziwe:

- [ ] Instalacja w czystym Pythonie 3.12 działa.
- [ ] Wszystkie testy, Ruff i mypy przechodzą.
- [ ] Pokrycie wynosi co najmniej 85%.
- [ ] Docker uruchamia tę samą komendę co środowisko lokalne.
- [ ] Wyszukiwanie 3 km wokół punktu we Wrocławiu generuje CSV, manifest i linki.
- [ ] CSV ma dokładnie ustalony schemat i poprawne polskie znaki w Excelu.
- [ ] Overture release i źródła/licencje są zachowane.
- [ ] Dokładny promień został przetestowany, nie jest samym bbox.
- [ ] W top 20 nie ma powtórzonego `overture_id` ani dwóch rekordów połączonych
      którąkolwiek regułą deduplikacji.
- [ ] Udział `is_chain=true` w top 20 wynosi najwyżej 20%.
- [ ] Buckety nie używają określenia `confirmed` bez ręcznej decyzji.
- [ ] Brak klucza Google nie psuje trybu `--enrich none`.
- [ ] Tryb Google przestrzega budżetu i nie zapisuje surowej odpowiedzi.
- [ ] Playwright i rozszerzenie Chrome nie są zależnościami projektu.
- [ ] README pozwala nowemu użytkownikowi wykonać pierwszy przebieg jedną komendą.
- [ ] Ręczna kalibracja obejmuje co najmniej 20 ocenionych wierszy, ma
      `target_precision >= 0.80`, `no_site_precision >= 0.70` oraz ważny
      `calibration.approved.json` ze zgodnym hashem.
- [ ] Pomiar 3 km bez Google trwa <= 300 s, nie licząc jednorazowej instalacji
      rozszerzenia DuckDB; czas i warunki pomiaru są w manifeście/raporcie.
- [ ] Każdy udany zestaw ma poprawny marker `.complete`; przerwany zapis nie ma go.
- [ ] `data_fresh_until` istnieje, a README wyjaśnia 30-dniową świeżość i ręczne
      usuwanie starych danych.

## 25. Dalszy rozwój po v1

Kolejność po potwierdzeniu wartości CSV:

1. `--district` i `--area-geojson` z dokładnym `point-in-polygon`.
2. Geokodowanie tekstowego adresu przez jawnie wybranego dostawcę.
3. Niezależna weryfikacja domen przez API wyszukiwarki z prawem do retencji wyników.
4. Sprawdzanie dostępności i jakości znalezionej domeny.
5. SQLite dla historii uruchomień i ręcznych werdyktów.
6. Prosty panel mapowy.
7. Dopiero na końcu automatyzacja cykliczna.

Nie rozpoczynać żadnego z tych punktów przed przejściem Definition of Done v1.

## 26. Źródła autorytatywne i zasada zmian zewnętrznych

Przy implementacji zewnętrznych integracji agent może opierać się wyłącznie na poniższych oficjalnych źródłach:

- Overture Places: <https://docs.overturemaps.org/guides/places/>;
- Overture taxonomy: <https://docs.overturemaps.org/guides/places/taxonomy/>;
- Overture Taxonomy schema reference (autorytatywne nazwy pól): <https://docs.overturemaps.org/schema/reference/places/types/taxonomy/>;
- Overture Taxonomy Browser: <https://docs.overturemaps.org/guides/places/taxonomy-browser/>;
- Overture STAC: <https://stac.overturemaps.org/catalog.json>;
- Overture release calendar i retencja: <https://docs.overturemaps.org/release-calendar/>;
- Overture DuckDB: <https://docs.overturemaps.org/getting-data/duckdb/>;
- Overture licencje i atrybucje: <https://docs.overturemaps.org/attribution/>;
- Google Text Search (New): <https://developers.google.com/maps/documentation/places/web-service/text-search>;
- Google Places policies: <https://developers.google.com/maps/documentation/places/web-service/policies>;
- Google Place IDs: <https://developers.google.com/maps/documentation/places/web-service/place-id>;
- Google pricing: <https://developers.google.com/maps/billing-and-pricing/pricing>.

Blogi, tutoriale, odpowiedzi Stack Overflow i kod przypadkowych repozytoriów nie mogą rozstrzygać kontraktów API. Jeżeli oficjalna dokumentacja różni się od niniejszego planu, agent ma:

1. zapisać dokładny link i datę sprawdzenia;
2. wskazać konkretny punkt planu, który stał się nieaktualny;
3. zaproponować najmniejszą zmianę zachowującą cel i testy;
4. wstrzymać implementację zależnego milestone’u do zatwierdzenia zmiany.
