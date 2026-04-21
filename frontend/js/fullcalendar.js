import { Calendar } from '@fullcalendar/core';
import allLocales from '@fullcalendar/core/locales-all';
import dayGridPlugin from '@fullcalendar/daygrid';
import listPlugin from '@fullcalendar/list';
import timeGridPlugin from '@fullcalendar/timegrid';

export function setupCalendar(domEl, events, initialDate, locale) {
  const calendar = new Calendar(domEl, {
    plugins: [dayGridPlugin, timeGridPlugin, listPlugin],
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
