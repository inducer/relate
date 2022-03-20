import { Calendar } from '@fullcalendar/core';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import listPlugin from '@fullcalendar/list';
import allLocales from '@fullcalendar/core/locales-all';

/* eslint-disable-next-line import/prefer-default-export */
export function setupCalendar(domEl, events, initialDate, locale) {
  const calendar = new Calendar(domEl, {
    plugins: [
      dayGridPlugin,
      timeGridPlugin,
      listPlugin,
    ],
    locales: allLocales,
    locale,
    initialView: 'dayGridMonth',
    headerToolbar: {
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,timeGridWeek,listWeek',
    },
    initialDate,
    events,
    defaultTimedEventDuration: '00:00:00.001',
  });
  calendar.render();
}
