import { useState, type ComponentType, type ReactNode } from 'react'
import { Button, type ButtonSize, type ButtonVariant } from '@/shared/ui/button/Button'
import type { IconProps } from '@/shared/ui/icon/createIcon'
import {
  ActivityIcon,
  AlertTriangleIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BellIcon,
  CalendarIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  CoffeeIcon,
  EyeIcon,
  GripVerticalIcon,
  InfoIcon,
  LinkIcon,
  LockIcon,
  MailIcon,
  MoonIcon,
  PlusIcon,
  RefreshIcon,
  RepeatIcon,
  SearchIcon,
  ShieldCheckIcon,
  SlidersIcon,
  SparklesIcon,
  SunIcon,
  TrendingUpIcon,
  UndoIcon,
  UserIcon,
  WifiOffIcon,
  XIcon,
  ZapIcon,
} from '@/shared/ui/icon/icons'
import { NavItem } from '@/shared/ui/nav-item/NavItem'
import * as Segment from '@/shared/ui/segment/Segment'
import { Toggle } from '@/shared/ui/toggle/Toggle'
import styles from './KitPage.module.css'

type Theme = 'dark' | 'light'

const THEMES: readonly { theme: Theme; title: string }[] = [
  { theme: 'dark', title: 'Тёмная тема' },
  { theme: 'light', title: 'Светлая тема' },
]

const COLOR_GROUPS: readonly { title: string; tokens: readonly string[] }[] = [
  {
    title: 'Поверхности',
    tokens: ['bg-base', 'bg-surface', 'bg-sidebar', 'bg-elevated', 'bg-overlay'],
  },
  {
    title: 'Текст и акцент',
    tokens: ['text-primary', 'text-secondary', 'text-tertiary', 'accent-solid', 'accent-text'],
  },
  {
    title: 'Циклы',
    tokens: ['bio-physical', 'bio-emotional', 'bio-intellectual', 'energy-high', 'now-line'],
  },
  {
    title: 'Типы задач',
    tokens: [
      'type-intellectual',
      'type-creative',
      'type-physical',
      'type-social',
      'type-routine',
      'type-rest',
    ],
  },
  {
    title: 'Статусы',
    tokens: ['status-success', 'status-warning', 'status-danger'],
  },
]

const TYPE_SCALE: readonly { className: string; label: string }[] = [
  { className: 'text-display', label: 'Display · Среда, 14 октября' },
  { className: 'text-title', label: 'Title · План на день' },
  { className: 'text-heading', label: 'Heading · Энергетический профиль' },
  { className: 'text-body', label: 'Body · Пик интеллектуального цикла' },
  { className: 'text-body-s', label: 'Body S · Рассчитан по дате рождения' },
  { className: 'text-label', label: 'Label · Добавить задачу' },
  { className: 'text-label-s', label: 'Label S · Перенести' },
  { className: 'text-caption', label: 'Caption · 7 задач · 6,5 ч запланировано' },
  { className: 'text-number-l', label: '+94 %' },
  { className: 'text-mono-m', label: '10:00–11:30' },
  { className: 'text-mono-s', label: '90 мин · интеллектуальная' },
]

const BUTTON_VARIANTS: readonly ButtonVariant[] = ['primary', 'secondary', 'ghost']
const BUTTON_SIZES: readonly ButtonSize[] = ['m', 's']

const ICONS: readonly [string, ComponentType<IconProps>][] = [
  ['sun', SunIcon],
  ['moon', MoonIcon],
  ['calendar', CalendarIcon],
  ['activity', ActivityIcon],
  ['sliders', SlidersIcon],
  ['plus', PlusIcon],
  ['lock', LockIcon],
  ['sparkles', SparklesIcon],
  ['clock', ClockIcon],
  ['chevron-right', ChevronRightIcon],
  ['chevron-left', ChevronLeftIcon],
  ['chevron-down', ChevronDownIcon],
  ['bell', BellIcon],
  ['check', CheckIcon],
  ['arrow-right', ArrowRightIcon],
  ['arrow-left', ArrowLeftIcon],
  ['info', InfoIcon],
  ['zap', ZapIcon],
  ['search', SearchIcon],
  ['x', XIcon],
  ['coffee', CoffeeIcon],
  ['undo', UndoIcon],
  ['refresh', RefreshIcon],
  ['wifi-off', WifiOffIcon],
  ['user', UserIcon],
  ['alert-triangle', AlertTriangleIcon],
  ['repeat', RepeatIcon],
  ['mail', MailIcon],
  ['trending-up', TrendingUpIcon],
  ['shield-check', ShieldCheckIcon],
  ['grip-vertical', GripVerticalIcon],
  ['eye', EyeIcon],
  ['link', LinkIcon],
]

function KitSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h3 className={`text-label-s ${styles.sectionTitle}`}>{title}</h3>
      {children}
    </section>
  )
}

function ColorTokens() {
  return (
    <div className={styles.colorGroups}>
      {COLOR_GROUPS.map((group) => (
        <div key={group.title} className={styles.colorGroup}>
          <span className="text-caption">{group.title}</span>
          <ul className={styles.swatches}>
            {group.tokens.map((token) => (
              <li key={token} className={styles.swatch}>
                <span className={styles.swatchColor} style={{ background: `var(--${token})` }} />
                <span className="text-mono-s">{token}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function TypeScale() {
  return (
    <ul className={styles.stack}>
      {TYPE_SCALE.map((item) => (
        <li key={item.className} className={item.className}>
          {item.label}
        </li>
      ))}
    </ul>
  )
}

function Buttons() {
  return (
    <div className={styles.stack}>
      {BUTTON_SIZES.map((size) => (
        <div key={size} className={styles.row}>
          {BUTTON_VARIANTS.map((variant) => (
            <Button key={variant} variant={variant} size={size}>
              <PlusIcon />
              Кнопка
            </Button>
          ))}
          <Button size={size} disabled>
            <PlusIcon />
            Недоступна
          </Button>
        </div>
      ))}
    </div>
  )
}

function Navigation() {
  return (
    <nav aria-label="Пример навигации" className={styles.nav}>
      <NavItem href="#today" aria-current="page">
        <SunIcon />
        Сегодня
      </NavItem>
      <NavItem href="#calendar">
        <CalendarIcon />
        Календарь
      </NavItem>
      <NavItem href="#biorhythms">
        <ActivityIcon />
        Биоритмы
      </NavItem>
      <NavItem href="#settings">
        <SlidersIcon />
        Настройки
      </NavItem>
    </nav>
  )
}

function Controls() {
  const [planByBiorhythms, setPlanByBiorhythms] = useState(true)
  const [sleepReminder, setSleepReminder] = useState(false)
  const [scale, setScale] = useState('week')

  return (
    <div className={styles.stack}>
      <label className={styles.toggleRow}>
        <span className="text-body-s">Учитывать биоритмы</span>
        <Toggle checked={planByBiorhythms} onCheckedChange={setPlanByBiorhythms} />
      </label>
      <label className={styles.toggleRow}>
        <span className="text-body-s">Подготовка ко сну</span>
        <Toggle checked={sleepReminder} onCheckedChange={setSleepReminder} />
      </label>
      <label className={styles.toggleRow}>
        <span className="text-body-s">Недоступно</span>
        <Toggle checked={false} onCheckedChange={setSleepReminder} disabled />
      </label>
      <Segment.Root value={scale} onValueChange={setScale} aria-label="Масштаб">
        <Segment.Item value="day">День</Segment.Item>
        <Segment.Item value="week">Неделя</Segment.Item>
        <Segment.Item value="month">Месяц</Segment.Item>
      </Segment.Root>
    </div>
  )
}

function Icons() {
  return (
    <ul className={styles.icons}>
      {ICONS.map(([name, Icon]) => (
        <li key={name} className={styles.icon} title={name}>
          <Icon />
          <span className="text-caption">{name}</span>
        </li>
      ))}
    </ul>
  )
}

function KitPanel({ theme, title }: { theme: Theme; title: string }) {
  return (
    <div data-theme={theme} className={styles.panel}>
      <h2 className="text-title">{title}</h2>
      <KitSection title="Цвета">
        <ColorTokens />
      </KitSection>
      <KitSection title="Типографика">
        <TypeScale />
      </KitSection>
      <KitSection title="Button">
        <Buttons />
      </KitSection>
      <KitSection title="Nav Item">
        <Navigation />
      </KitSection>
      <KitSection title="Toggle и Segment">
        <Controls />
      </KitSection>
      <KitSection title="Иконки">
        <Icons />
      </KitSection>
    </div>
  )
}

export function KitPage() {
  return (
    <main className={styles.page}>
      <h1 className="visually-hidden">UI-кит «Идеальный день»</h1>
      {THEMES.map((item) => (
        <KitPanel key={item.theme} theme={item.theme} title={item.title} />
      ))}
    </main>
  )
}
