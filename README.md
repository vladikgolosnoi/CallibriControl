# CallibriControl

Жестовое управление компьютером на базе датчика Callibri (EMG + MEMS). Курсор, клики, перелистывание слайдов, медиа, браузер и игровые профили. Калибровка под пользователя (baseline/MVC), адаптивные пороги, готовые схемы действий.

## Что уже работает
- Подключение к Callibri, стрим EMG (raw/envelope) и MEMS (наклоны, аксель, кватернионы).
- Калибровка EMG (baseline/MVC) и нейтральной ориентации; профили чувствительности (ULTRA/SENSITIVE/NORMAL/etc.).
- Эмуляция клавиатуры/мыши: клики, drag, скролл, стрелки/WASD, медиа, браузер, презентации.
- Жесты: MUSCLE_FLEX/HOLD/RELEASE, DOUBLE/TRIPLE_FLEX, TILT_UP/DOWN/LEFT/RIGHT, SHAKE, FLEX+TILT комбо.
- Профиль презентаций: махи влево/вправо или FLEX+мах — листают слайды (PageDown/PageUp).
- Веб/GUI режимы и демо без датчика (CLI — основной вход).

## Установка
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Быстрый старт (CLI)
- Найти датчики: `python3 -u main.py --scan`
- Стрим EMG: `python3 -u main.py --stream --address <ADDR>`
- Управление курсором (наклоны):  
  `python3 -u main.py --control --address <ADDR> --profile ULTRA_SENSITIVE --control-profile MOUSE_CONTROL --mouse-speed 40 --mouse-deadzone 4 --swap-axes --invert-y`
- Презентации (PowerPoint/Keynote/Slides):  
  `python3 -u main.py --control --address <ADDR> --profile ULTRA_SENSITIVE --control-profile PRESENTATION --tilt-deg 18 --mouse-speed 0`
  - Мах влево → следующий (PageDown), мах вправо → предыдущий (PageUp).  
  - Сжатие + мах (FLEX_TILT_LEFT/RIGHT) дублирует листание.

## Жесты и калибровка
- EMG-порог зависит от профиля: ULTRA_SENSITIVE ~0.8% MVC включение, ~0.4% выключение (низкие усилия).
- Калибровка: 2 c relax → 2 c max сжатие; потом нейтральная поза для ориентации (наклон запоминается).
- Курсовое управление сейчас без EMG-гейта: движение всегда по MEMS, а клики/drag — по EMG-жестам.

## Профили действий (встроенные)
- `MOUSE_CONTROL`: FLEX=ЛКМ, HOLD=drag, DOUBLE_FLEX=двойной, TRIPLE_FLEX=ПКМ, SHAKE=scroll.
- `PRESENTATION`: махи и FLEX+махи листают (PageDown/PageUp), FLEX=Right, DOUBLE_FLEX=Left.
- `MEDIA`: play/pause (space), next/prev (right/left), mute/vol.
- `BROWSER`: enter, Ctrl+L, Ctrl+T, Alt+←/→, Ctrl+Tab/Shift+Tab.
- `GAMING_WASD`, `GAMING_ARROWS`, `ACCESSIBILITY` — см. `callibri_control/control/profiles.py`.

## Полезные флаги и тюнинг
- `--tilt-deg <deg>` — порог наклона для TILT (меньше = чувствительнее).  
- `--mouse-speed`, `--mouse-deadzone`, `--mouse-angle-max`, `--swap-axes`, `--invert-y`, `--mouse-use-yaw`.  
- `--move-threshold <0..1>` — порог движения курсора как доля MVC (если нужно вернуть гейтинг).  
- `--envelope` — использовать огибающую EMG, если raw слабый/шумный.  
- Презентации: `--mouse-speed 0` чтобы не двигать курсор, только листать жестами.

## Структура проекта
- `main.py` — CLI/web/gui/demo точка входа.  
- `callibri_control/core` — SensorManager, потоки данных, калибровка.  
- `callibri_control/detection` — адаптивные пороги, детектор жестов, усталость.  
- `callibri_control/control` — эмуляторы мыши/клавиатуры, маппинг действий, профили.  
- `web/` — веб-интерфейс/презентация.

## Типовые сценарии
- **Демонстрация/слайды:** PRESENTATION, махи или FLEX+мах, `--tilt-deg 15..20`, `--mouse-speed 0`.  
- **Доступность:** ACCESSIBILITY, порог ULTRA/SENSITIVE, щадящие пороги EMG.  
- **Игры:** GAMING_WASD/ARROWS или MOUSE_CONTROL + двойное/тройное FLEX для кликов.  
- **Медиа:** MEDIA профиль — play/pause/next/prev/volume с жестов.

## Публикация в GitHub (ручной пуш)
```
git init
git add .
git commit -m "Initial import: CallibriControl"
git branch -M main
git remote add origin https://github.com/vladikgolosnoi/CallibriControl.git
git push -u origin main
```
