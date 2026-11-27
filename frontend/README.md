# Веб-интерфейс Камертона

React Native Web отвечает за оболочку, компоновку и типографику экранов. Для полей, кнопок и таблиц используются компоненты shadcn/ui из реестра Radix. Vite разрешает импорт `react-native` через `react-native-web`. Приложение и вход владельца имеют отдельные точки входа. Основные экраны загружаются по вкладкам.

| Путь | Назначение |
| --- | --- |
| `src/app/` | Сессия, навигация, состояние сервиса и события SSE |
| `src/features/` | Диктовка, сравнение, модели, настройки, глоссарий, подключение API, мониторинг, журнал и вход |
| `src/shared/` | Транспорт API и словари локализации |
| `src/components/native/` | Общие компоненты на `View` и `Text` с семантическими ролями |
| `src/components/ui/` | Компоненты официального реестра shadcn/ui |
| `src/styles/` | Тема, оболочка, общие стили экранов и входа |
| `public/` | AudioWorklet для микрофона |

## Локальный запуск

Из корня репозитория:

```sh
uv sync
npm --prefix frontend ci
uv run uvicorn console.main:create_app --factory --host 127.0.0.1 --port 8080
```

В другом терминале:

```sh
npm --prefix frontend run dev
```

Vite проксирует API и SSE в локальный FastAPI на порту 8080. Для локального Vite используйте профиль без доступа владельца. Проверки профиля владельца выполняются через FastAPI с собранными файлами и его обычной HTTPS-конфигурацией.

```sh
npm --prefix frontend run build
uv run --with playwright python -m pytest
```

FastAPI раздает `frontend/dist/`. Ссылки в HTML содержат отпечатки ресурсов Vite. До входа владельца доступен только граф ресурсов страницы входа из манифеста сборки. Docker собирает фронтенд на отдельном этапе, а в рабочий образ копирует результат.

Страница входа и консоль подключают внешний лист стилей, в который React Native Web 0.21.4 добавляет правила через CSSOM. Это сохраняет действующую CSP прокси. При обновлении React Native Web проверьте, что библиотека по-прежнему использует этот лист, и прогоните `test_browser_loads_native_stylesheet_with_public_csp` в Chrome и WebKit. [Исходник React Native Web 0.21.4](https://github.com/necolas/react-native-web/blob/0.21.4/packages/react-native-web/src/exports/StyleSheet/dom/createCSSStyleSheet.js)

Скиллы ставятся локально из корня проекта:

```sh
npx skills add shadcn/ui --skill shadcn -a codex -y --copy
npx skills add https://github.com/callstackincubator/agent-skills --skill react-native-best-practices -a codex -y --copy
```

[Конфигурация shadcn/ui](https://ui.shadcn.com/docs/components-json) · [Рекомендации по работе со сборкой](https://www.skills.sh/callstackincubator/agent-skills/react-native-best-practices)
