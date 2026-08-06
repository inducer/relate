import { Calendar } from 'fullcalendar';
import dayGridPlugin from 'fullcalendar/daygrid';
import listPlugin from 'fullcalendar/list';
import allLocales from 'fullcalendar/locales-all';
import themePlugin from 'fullcalendar/themes/classic';
import timeGridPlugin from 'fullcalendar/timegrid';

import 'fullcalendar/skeleton.css';
import 'fullcalendar/themes/classic/theme.css';
import 'fullcalendar/themes/classic/palette.css';

export function setupCalendar(domEl, events, initialDate, locale) {
  const calendar = new Calendar(domEl, {
    plugins: [dayGridPlugin, timeGridPlugin, listPlugin, themePlugin],
    locales: allLocales,
    initialView: 'dayGridMonth',
    headerToolbar: {
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,timeGridWeek,listWeek',
    },
    initialDate,
    events,
    locale,
  });
  calendar.render();
}
