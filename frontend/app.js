'use strict';
const $ = (id) => document.getElementById(id);
const state = {offset: 0, limit: 10, filter: '', loaded: false, editId: null, deleteId: null, busy: false};
const number = (value) => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(value);
const date = (value) => new Date(value).toLocaleString('ru-RU', {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'});
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = !message; }
async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type':'application/json'}, signal: AbortSignal.timeout(60000), ...options});
  if (response.status === 204) return null;
  let data;
  try { data = await response.json(); } catch { throw new Error('Сервис временно недоступен. Проверьте, что все контейнеры работают.'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте введённые данные и повторите запрос.');
  return data;
}
function messageOf(error) { return ['TimeoutError','AbortError'].includes(error.name) ? 'Время ожидания истекло. Повторите запрос позже.' : error instanceof TypeError ? 'Нет связи с приложением. Проверьте подключение и контейнеры.' : error.message; }
async function action(work) {
  if (state.busy) return;
  state.busy = true;
  const previousNavigation = {offset:state.offset, filter:state.filter};
  // Сохраняем прежнее состояние кнопок пагинации.
  const buttons = [...document.querySelectorAll('button')];
  const disabled = buttons.map((button) => button.disabled);
  buttons.forEach((button) => {button.disabled = true;});
  document.querySelector('main').setAttribute('aria-busy', 'true');
  notice('');
  try { await work(); } catch (error) {
    state.offset = previousNavigation.offset; state.filter = previousNavigation.filter;
    notice(messageOf(error), true);
  }
  finally {
    buttons.forEach((button, index) => {if (button.isConnected) button.disabled = disabled[index];});
    state.busy = false;
    document.querySelector('main').removeAttribute('aria-busy');
    if (state.loaded) updatePagination();
  }
}
function text(tag, content, className) { const el = document.createElement(tag); el.textContent = content; if (className) el.className = className; return el; }
function showWeather(record) {
  $('weather-empty').hidden = true; $('weather-result').hidden = false;
  $('result-city').textContent = record.city;
  $('result-location').textContent = [record.region, record.country].filter(Boolean).join(', ');
  $('temperature').textContent = `${number(record.temperature)}°`;
  $('description').textContent = record.description;
  $('feels-like').textContent = `${number(record.feels_like)} °C`;
  $('humidity').textContent = `${record.humidity} %`;
  $('wind-speed').textContent = `${number(record.wind_speed)} м/с`;
  $('observed-at').textContent = `Данные на ${date(record.observed_at)}`;
  $('weather-symbol').textContent = record.weather_code === 0 ? '☀' : record.weather_code >= 71 && record.weather_code <= 77 ? '❄' : record.weather_code >= 51 ? '☂' : '☁';
}
async function fetchWeather(city, locationId) {
  const record = await api('/api/weather', {method:'POST', body:JSON.stringify({city, location_id:locationId})});
  showWeather(record); $('locations').hidden = true;
  notice(`Погода в городе ${record.city} сохранена в истории. Запись № ${record.id}.`);
  if (state.loaded) {state.offset = 0; await loadHistory();}
}
async function searchWeather() {
  const city = $('city').value.trim();
  if (city.length < 2) throw new Error('Введите название города длиной от 2 символов.');
  const {items} = await api(`/api/cities?q=${encodeURIComponent(city)}`);
  $('location-list').replaceChildren(); $('locations').hidden = true;
  if (!items.length) throw new Error('Город не найден. Проверьте название или введите его латиницей.');
  if (items.length === 1) return fetchWeather(city, items[0].id);
  for (const item of items) {
    const button = text('button', [item.name, item.region, item.country].filter(Boolean).join(', '));
    button.type = 'button'; button.addEventListener('click', () => action(() => fetchWeather(city, item.id)));
    $('location-list').append(button);
  }
  $('locations').hidden = false;
  notice('Найдено несколько населённых пунктов. Выберите нужный из списка.');
  $('location-list').firstElementChild.focus();
}
function updatePagination() {
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + state.limit >= state.total;
}
function renderHistory(data) {
  state.total = data.total; state.loaded = true;
  $('history-count').textContent = data.total; $('history-count').hidden = false;
  $('history-body').replaceChildren();
  $('history-table-wrap').hidden = !data.items.length; $('history-empty').hidden = !!data.items.length;
  if (!data.items.length) {
    $('history-empty').querySelector('h3').textContent = state.filter ? 'Совпадений не найдено' : 'История пока пуста';
    $('history-empty').querySelector('p').textContent = state.filter ? 'Измените название города или очистите поиск.' : 'Получите погоду, чтобы сохранить первый запрос.';
  }
  for (const record of data.items) {
    const row = document.createElement('tr');
    const city = document.createElement('td'); city.append(text('strong', record.city), text('small', [record.region,record.country].filter(Boolean).join(', ')), text('small', date(record.requested_at)));
    const weather = document.createElement('td'); weather.append(text('strong', `${number(record.temperature)} °C`), text('span', record.description), text('small', `${record.humidity} % · ${number(record.wind_speed)} м/с`));
    if (record.is_demo) weather.append(text('small', 'Учебный пример', 'demo-label'));
    else weather.append(text('small', record.source));
    const observed = text('td', date(record.observed_at));
    const note = text('td', record.note || 'Нет заметки', 'note-cell');
    const actions = document.createElement('td'); const controls = document.createElement('div'); controls.className = 'row-actions';
    const edit = text('button', 'Заметка'); edit.type = 'button'; edit.setAttribute('aria-label', `Изменить заметку: ${record.city}, запись ${record.id}`);
    edit.addEventListener('click', () => {if(state.busy)return;state.editId = record.id; $('note-city').textContent = `${record.city} · ${date(record.requested_at)}`; $('note-text').value = record.note; $('note-error').hidden = true; $('edit-dialog').showModal();});
    const remove = text('button', 'Удалить'); remove.type = 'button'; remove.setAttribute('aria-label', `Удалить запрос: ${record.city}, запись ${record.id}`);
    remove.addEventListener('click', () => {if(state.busy)return;state.deleteId = record.id; $('delete-city').textContent = `${record.city} · ${date(record.requested_at)}`; $('delete-error').hidden = true; $('delete-dialog').showModal();});
    controls.append(edit, remove); actions.append(controls); row.append(city, weather, observed, note, actions); $('history-body').append(row);
  }
  $('history-button').textContent = '↻ Обновить историю';
  $('pagination').hidden = data.total === 0;
  $('page-info').textContent = `${state.offset + 1}–${state.offset + data.items.length} из ${data.total} · время браузера`;
  updatePagination();
}
async function loadHistory() {
  const params = new URLSearchParams({limit:state.limit, offset:state.offset, city:state.filter});
  const data = await api(`/api/history?${params}`);
  if (state.offset > 0 && !data.items.length) {state.offset = Math.max(0, state.offset - state.limit); return loadHistory();}
  renderHistory(data);
}
$('weather-form').addEventListener('submit', (event) => {event.preventDefault(); action(searchWeather);});
document.querySelectorAll('[data-city]').forEach((button) => button.addEventListener('click', () => {$('city').value = button.dataset.city; action(searchWeather);}));
$('history-button').addEventListener('click', () => action(loadHistory));
$('filter-form').addEventListener('submit', (event) => {event.preventDefault(); action(async () => {state.filter = $('history-filter').value.trim();state.offset = 0;await loadHistory();});});
$('previous').addEventListener('click', () => action(async () => {state.offset = Math.max(0, state.offset - state.limit); await loadHistory();}));
$('next').addEventListener('click', () => action(async () => {state.offset += state.limit; await loadHistory();}));
$('cancel-note').addEventListener('click', () => $('edit-dialog').close());
$('cancel-delete').addEventListener('click', () => $('delete-dialog').close());
$('note-form').addEventListener('submit', (event) => {
  event.preventDefault(); action(async () => {
    try {await api(`/api/history/${state.editId}`, {method:'PATCH',body:JSON.stringify({note:$('note-text').value})});}
    catch (error) {$('note-error').textContent = messageOf(error); $('note-error').hidden = false; return;}
    $('edit-dialog').close(); notice('Заметка сохранена.'); await loadHistory();
  });
});
$('confirm-delete').addEventListener('click', () => action(async () => {
  try {await api(`/api/history/${state.deleteId}`, {method:'DELETE'});}
  catch (error) {$('delete-error').textContent = messageOf(error); $('delete-error').hidden = false; return;}
  $('delete-dialog').close(); notice('Запрос удалён из истории.'); await loadHistory();
}));
