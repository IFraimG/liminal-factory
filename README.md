# Liminal Factory — macOS MVP

Локальное приложение Tauri 2 / React / TypeScript с Python sidecar, SQLite, параллельным DAG и ручными утверждениями музыки и визуальной сцены. Здесь находится исполняемый проект, а не макет. Полный производственный запуск требует внешних CLI, авторизованного AI-провайдера, YouTube API key и лицензированного Unity с графическим устройством.

## Быстрый запуск разработки

Требуются macOS, Xcode Command Line Tools, Node.js 20.19+ / npm, Rust stable, Python 3.11+.

```bash
npm install
npm run tauri dev
```

Первый запуск автоматически создаёт `.venv`, устанавливает Python-зависимости и собирает sidecar. Кэш npm находится внутри `work/`, а не в домашнем каталоге. На машине разработки Rust был установлен в `work/cargo` и `work/rustup`; wrapper использует его, если он существует. На другой машине установите Rust стандартным способом с официального rustup.rs.

```bash
npm run build               # TypeScript и production frontend
npm test                    # реальные проверки backend и коротких FFmpeg media
npm run tauri build         # Python sidecar + release .app и .dmg
```

Сборки находятся в `src-tauri/target/release/bundle/`. Python включён в приложение через PyInstaller **onedir**, включая numpy, soundfile и нативные библиотеки. Он находится в `Contents/Resources/backend/`; отдельный Python конечному пользователю не нужен. One-file намеренно не используется: его semaphore/extraction механизм запрещён в среде разработки. FFmpeg, FFprobe, yt-dlp, Herdr, Codex/Gemini и Unity являются проверяемыми внешними prerequisite и в приложение не включены.

## Настройка

1. Откройте Settings, выберите отдельную директорию проектов и сохраните настройки.
2. Настройте пути внешних инструментов и нажмите Test Connection для каждого. Unity автоматически ищется в `/Applications/Unity/Hub/Editor/*/Unity.app/Contents/MacOS/Unity`.
3. Установите **Herdr TUI CLI** из официальной документации. Наличие приложения `Herdr.app` либо другого исполняемого файла `hc` не подтверждает совместимость. Требуются команды `workspace create`, `agent start --kind … --pane …`, `agent prompt/get/read/send-keys` и `pane close`. Запустите Herdr server самостоятельно согласно его документации. Приложение не перезапускает чужие сессии.
4. Авторизуйте Codex либо Gemini в их терминальном CLI. Выберите kind и идентификатор модели; для отдельных задач можно переопределить модель. Herdr использует каноническое имя executable. Директория настроенного CLI передаётся в PATH новой workspace; имя файла должно быть `codex`/`gemini`.
5. Убедитесь, что выбранный agent/model действительно умеет просматривать локальные изображения, и включите соответствующий флажок. Без этого visual analysis недоступен и production не начнётся.
6. В Google Cloud включите YouTube Data API v3, создайте и ограничьте ключ этим API. Сохраните его в Settings → YouTube. Он хранится только в нативном macOS Keychain (Security framework через keyring macOS backend).
7. Активируйте Unity Personal/Pro в Unity Hub. Нужен работающий графический рендеринг. `-nographics` не используется и не подходит для захвата кадров.

## Производство эпизода

- New Episode: HTTPS YouTube video URL, начало MM:SS/HH:MM:SS, длительность анализа, согласие на получение фрагмента, одно или несколько изображений, канал `/@handle` либо `/channel/UC…`.
- Изображения поддерживают drag and drop, миниатюры, порядок и удаление. Они копируются в workspace. После начала анализа references блокируются.
- Выберите стиль, длительность, FPS, разрешение, audio mode, длину визуальной петли и при желании директорию экспорта. Save episode draft сохраняет эпизод без запуска внешних задач. Start Production проверяет зависимости и запускает DAG.
- Audio Reference и Visual Reference одновременно с Channel Reference выполняют независимые работы. Semaphore ограничивает общее число активных задач; это также ограничивает число агентов.
- Audio analysis использует фактические RMS, FFT spectral centroid, динамический диапазон и оценку темпа по autocorrelation. Это **не** семантическое прослушивание моделью; для ambient оценка темпа может быть ненадёжной. Ограничения записываются в JSON.
- Music Agent создаёт оригинальный бриф и несколько Suno prompts. Их можно редактировать, сохранять и копировать. Open Suno открывает официальный сайт. Генерируйте музыку вручную и импортируйте WAV/MP3. Автоматизации браузера Suno нет.
- Approve music фиксирует SHA-256 музыки и брифа. Следующая задача автоматически собирает WAV заданной длительности.
- Visual Agent реально просматривает изображения через настроенный CLI. Unity Agent выбирает ограниченный JSON scene spec: палитру, туман, камеру, шаг колонн. Проверенный C# template создаёт terrain, архитектуру, материалы, свет, fog, камеру и периодическое движение. Произвольный C# от модели не исполняется.
- Unity создаёт preview; image-capable agent сравнивает первый кадр с references и сохраняет Visual QA. После Approve visual сцена рендерит петлю в целевом разрешении, затем FFmpeg собирает MP4.
- Metadata ждёт музыкального и визуального брифов, получает все доступные публичные заголовки из uploads playlist с pagination/cache, создаёт пять уникальных заголовков, описание и хэштеги. Проверяется формат `#tag, #tag` и отсутствие дословных совпадений с источниками. Прогноз эффективности не заявляется.
- Final Assembly ждёт все ветки. Результат — `output/final.mp4` и `output/metadata.json`. Дополнительный экспорт создаёт уникальную папку `liminal-<episode-id>` без перезаписи существующей.

В Episode Details доступны реальные статусы, время задач, structured results, логи, playable audio/video, файлы, Retry Task, Cancel Task, Approve, Request Changes и Open Output Folder. Request Changes передаёт текст агенту и инвалидирует зависимые задачи, включая metadata/final assembly. Музыку можно удалить и импортировать заново до утверждения.

## Аудио и видео

Seamless Loop ищет тихие окна у границ, делает перекрытие tail/head и записывает повторяемый cycle на диск. Финальный WAV не создаётся целиком в памяти. FFmpeg повторяет его до нужной длительности; two-pass loudnorm целится в -18 LUFS / -1.5 dBTP. Финальный проход измеряет true peak, sample peak и точную длительность. Слишком тихий/некорректный источник отклоняется.

Ambient Evolution добавляет отдельную детерминированную плавную амплитудную вариацию до 2.5% с периодом 125 секунд. Multi-track сначала сшивает несколько утверждённых файлов через crossfade и затем строит петлю. Это минимальные, предсказуемые преобразования; сложной генеративной аранжировки в MVP нет.

Unity снимает кадры в batchmode через Camera.Render/RenderTexture. Все движения определяются фазой одного периода и не накапливают время. C# сохраняет сцену `unity-project/Assets/Liminal.unity`, которую можно открыть в Editor. Требуется лицензия и графический device; ошибка возвращается явно с Unity log.

FFmpeg повторяет короткий визуальный цикл, кодирует H.264/AAC с требуемым FPS/разрешением, затем FFprobe проверяет streams/codecs/duration/resolution/FPS, а FFmpeg декодирует начало, середину и конец файла. Час уникальных кадров не рендерится.

## Надёжность и безопасность

- Loopback HTTP на случайном порту; два UUID формируют bearer token. Токен передаётся sidecar через environment, а webview — через единственную Rust bootstrap command. CORS/CSP ограничивают источники. Media range requests поддерживаются FileResponse; для тегов audio/video используется token URL, access logs выключены.
- В JavaScript нет shell/filesystem capabilities. Нативным диалогам разрешён только выбор файлов/каталогов. Rust-команда открытия сайта фиксирована на Suno, backend открывает только папку существующего эпизода.
- subprocess вызывается списком аргументов без shell; процессы имеют отдельную process group, timeout и рекурсивную отмену. Секреты не передаются в CLI аргументах и не сохраняются в логах.
- Строгий HTTPS/YouTube whitelist, защита от path traversal и symlink escape, проверка содержимого изображений/аудио, ограничения импорта 70 MB и 40 MP.
- Reference data не считаются инструкциями. Модели получают явную политику; код сцены фиксирован, их JSON проходит Pydantic validation. Автоматической публикации нет.
- SQL WAL хранит состояния, identity pane/agent, артефакты и structured logs. Backend lock исключает два orchestrator для одной data folder.
- После перезапуска прерванные локальные операции переходят в Failed с требованием Retry. Сохранённые Herdr identity сверяются с CLI; проверяемый агент останавливается перед повтором. Произвольный сохранённый PID не используется для kill. Если Herdr недоступен, интерфейс требует ручной проверки. Это безопасное восстановление к явному повтору, а не продолжение прерванного FFmpeg с середины.
- Каждая попытка агента имеет уникальный результат JSON. `idle`/`done` без валидного файла не считаются успехом. Approved-файлы повторно проверяются по SHA-256 перед обработкой/сборкой.
- Мок Herdr существует только как test dependency; production UI не может выбрать его.

## Данные

По умолчанию: `~/Library/Application Support/Liminal Factory/factory.sqlite3`; эпизоды находятся в подпапке `episodes/`. Путь проектов задаётся до создания первого эпизода. Смена root при существующих эпизодах блокируется, чтобы не терять связь с файлами. Для изолированной проверки можно перед запуском задать `LIMINAL_DATA="$PWD/work/runtime"`.

```text
backend/                  API, schemas, SQLite, DAG, adapters, media
src/                      React UI, typed API, navigation, styles
src-tauri/                native host, minimal capabilities, packaging
unity-template/           reproducible C# procedural scene
scripts/                  bootstrap, PyInstaller build, hour stress test
tests/                    security, DAG, API, Herdr contract, actual FFmpeg
IMPLEMENTATION_PLAN.md    implementation / validation checklist
VERIFICATION.md           observed checks and outstanding prerequisites
```

## Ограничения текущей версии

Нет гарантий semantic audio understanding, расширенной генерации Unity-кода, автоматического Suno, публикации на YouTube, частичного resume render, агента без авторизации или работы без внешних инструментов. Appearance фиксирован в dark mode; output defaults задаются в форме эпизода. Режим preview — та же процедура с меньшим разрешением. Модель может предложить visual QA правки, но их применение требует Request Changes и нового scene spec. Изображения обрабатываются внешним модельным провайдером только при явном запуске производства.

Локальная сборка не равна production distribution. Для распространения нужны Apple Developer signing/notarization, проверка лицензий внешних компонентов и тесты на целевых Intel/Apple Silicon машинах. Текущая сборка предназначена для этой Apple Silicon macOS-среды.

## Официальная документация

- [Herdr agent automation](https://herdr.dev/tui/docs/agent-automation/) и [CLI reference](https://herdr.dev/tui/docs/cli-reference/)
- [Tauri 2 — external binaries](https://v2.tauri.app/develop/sidecar/) и [resources](https://v2.tauri.app/develop/resources/)
- [YouTube playlistItems.list](https://developers.google.com/youtube/data/reference/rest/v3/playlistItems/list)
