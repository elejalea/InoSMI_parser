#!/usr/bin/python
# -*- coding: utf-8 -*

import sys

import re

import time

import os
import traceback

from bs4 import BeautifulSoup

# Модуль делает http запросы
import urllib.request
import unicodedata

# Константы
URL = 'https://inosmi.ru'
# Заводим словарь для пополнения в дальнейшем ссылками на другие оригинальные издания
PAPER_ORIGINAL_LINKS_PREFIX = {'yle_fi': 'https://yle.fi/'}
# Пауза, чтобы не забрасывать сайт запросами
PAUSE_SEC = 2
# Ключевые слова "Читать также по теме" в оригинальной статье, по которым обрезаем  
READ_NEXT_WORDS = ['Lue myös:', 'Lue myös', 'Lue lisää:', 'Lisää aiheesta:', 'Lue lisää aiheesta:']
METADATA_FILENAME = 'metadata.csv'
# Разделитель в csv
DELIMITER = ';'
# Ссылка на источник оригинала в переводе перед заголовком
YLE_FI_PREFIX = 'Yle (Финляндия): '
# Ссылка на источник оригинала в переводе после заголовка
YLE_FI_SUFFIX = '(Yle, Финляндия)'


# получить HTML страницы
def get_article_links(all_articles_url):
    next_link = None
    article_links = []

    request = urllib.request.Request(all_articles_url)
    try:
        response = urllib.request.urlopen(request)
        html_bytes = response.read()
        html_str = html_bytes.decode("utf8")
        soup = BeautifulSoup(html_str, 'html.parser')
        for header in soup.find_all('h1', {'class' : 'rubric-list__article-title rubric-list__article-title_small'}):
            article_links.append(URL+header.a['href'])
        next_page_footer = soup.find('footer', {'class' : 'rubric-list__get-more'})
        if next_page_footer is not None:
            next_link = next_page_footer.a['href']
            if next_link != '':
                next_link = URL + '/' + next_link
    except Exception as e:
        print("ERROR_LINKS:" + all_articles_url + ":" + str(e))

    return article_links, next_link

# Парсим переводную статью в ИноСМИ
def parse_article(article_link, paper_name):
    article_data = {}
    article_data['is_good'] = True
    request = urllib.request.Request(article_link)
    try:
        article_data_rus = {}
        article_data_original = {}
        # Делаем http запрос к адресу страницы
        response = urllib.request.urlopen(request)
        html_bytes = response.read()
        html_str = html_bytes.decode("utf8")
        # Парсим полученную страницу
        soup = BeautifulSoup(html_str, 'html.parser')
        # Получаем ссылку на кнопку "Загрузить ещё"
        original_source = soup.find('div', {'class': 'article-footer__source'})
        original_source_link = original_source.a['href']
        article_data['original_source_link'] = original_source_link
        # Проверяем, что статья на финском
        if not is_good_link(original_source_link, paper_name):
            article_data['is_good'] = False
            return article_data
        article_data_original['link'] = original_source_link
        article_data_original['source'] = paper_name
        # Парсим оригинальную статью
        parse_original_article(article_data_original)
        # Парсим поля русской статьи
        article_data_rus['link'] = article_link
        header_title = soup.find('h1', {'class': 'article-header__title'})
        article_data_rus['header_title'] = normalize_russian_header(header_title.text)
        article_author = soup.find('address', {'class': 'article-header__author-name author'})
        article_data_rus['article_author'] = article_author.text
        article_date = soup.find('time', {'class': 'article-header__date'})
        article_data_rus['article_date'] = article_date.text
        # Получаем текст статьи, в зависимости от вёрстки может быть в тэгах с разными классами
        article_body = soup.find('div', {'class': 'article-body article-body_indented'})
        if article_body is None:
            article_body = soup.find('div', {'class': 'article-body'})
        # Удаляем дисклэймер ИноСМИ
        article_disclaimer = article_body.find('div', {'class' : 'article-disclaimer'})
        if article_disclaimer is not None:
            article_disclaimer.extract()
        article_text = ''
        for article_p in article_body.find_all('p'):
            # В верстке содержится выносной абзац "Контекст", его содержимое мы пропускаем
            if not is_aside_paragraph(article_p):
                article_text += '\r\n' + article_p.text.strip()
        # Удаляем лишние пробелы и преобразуем HTML entities в символы юникода
        article_text = unicodedata.normalize("NFKD", article_text.strip())
        article_data_rus['article_text'] = article_text
        article_data['rus'] = article_data_rus
        article_data['original'] = article_data_original
    # Обработка ошибок в ходе парсинга (отсутствие ссылки на финский оригинал; ссылка на русскоязычный оригинал в финском инфоагенстве и т.п.)
    except Exception as e:
        print("ERROR PARSING RUSSIAN: " + article_link + ":" + str(e))
    return article_data

# Парсим оригинальную статью
def parse_original_article(article_data_original):
    article_data_original['is_good'] = True
    link = article_data_original['link']
    source = article_data_original['source']
    # Защита от попадания статей не обрабатываемого нами издания
    if source != 'yle_fi':
        raise Exception('Cannot parse ' + link)
    request = urllib.request.Request(link)
    try:
        response = urllib.request.urlopen(request)
        html_bytes = response.read()
        html_str = html_bytes.decode("utf8")
        soup = BeautifulSoup(html_str, 'html.parser')
        # В зависимости от вёрстки заголовок статьи может быть в тэгах разных классов
        original_header = soup.find('h1', {'class': 'yle__article__heading yle__article__heading--h1'})
        if original_header is None:
            original_header = soup.find('h1', {'class': 'node-title ydd-article__title'})
        # В зависимости от вёрстки ФИ автора статьи может быть в тэгах разных классов и може быть разделён на тэги Ф и И или может идти вместе
        original_author = soup.find('span', {'class' : "yle__article__author__name__text"})
        if original_author is None:
            original_author_firstname = soup.find('span', {'itemprop' : "givenName"})
            original_author_lastname = soup.find('span', {'itemprop': "familyName"})
            # Склеиваем ФИ
            original_author_text = original_author_firstname.text + " " + original_author_lastname.text
        else:
            original_author_text = original_author.text
        # В зависимости от вёрстки дата выхода статьи может быть в тэгах разных классов
        original_date = soup.find('span', {'class' : "yle__article__date--published" })
        if original_date is None:
            original_date = soup.find('time', {'itemprop' : "datePublished"})
        original_body = ''
        # Склеиваем из разных абзацев цельную статью
        for article_p in soup.find_all('p', {'class' : "yle__article__paragraph"}):
            # Удаляем невидимые слова "Перейти на другой ресурс", указывающие на внешние ссылки
            extra_link_spans = article_p.find_all('span', {'class': 'yle__accessibilityText'})
            for extra_link_span in extra_link_spans:
                extra_link_span.extract()
            article_p_text = article_p.text.strip()
            if article_p_text in READ_NEXT_WORDS:
                break
            original_body += '\r\n' + article_p_text
        original_body = original_body.strip()
        # Другой тип верстки, ищем абзацы иначе
        if original_body == "":
            original_body_tag = soup.find('div', {'class' : "ydd-article__body"})
            # Склеиваем из разных абзацев цельную статью
            for article_p in original_body_tag.find_all('p'):
                # Удаляем невидимые слова "Перейти на другой ресурс", указывающие на внешние ссылки
                extra_link_spans = article_p.find_all('span', {'class': 'yle__accessibilityText'})
                for extra_link_span in extra_link_spans:
                    extra_link_span.extract()
                article_p_text = article_p.text.strip()
                if article_p_text in READ_NEXT_WORDS:
                    break
                original_body += '\r\n' + article_p_text
            original_body = original_body.strip()

        article_data_original['header_title'] = original_header.text
        article_data_original['article_author'] = original_author_text
        article_data_original['article_date'] = normalize_yle_fi_date(original_date.text)
        article_data_original['article_text'] = original_body

    except Exception as e:
        print("ERROR:" + link + ':' + str(e))
        traceback.print_exc()
        article_data_original['is_good'] = False

# Изменяем формат даты в оригинальной статье, содержавший время публикации
def normalize_yle_fi_date(original_date):
    norm_orig_date = original_date.split(' ')[0]
    return norm_orig_date

# Запись текстов в txt
def write_article_to_file(article_data, folder):
    article_data_rus = article_data['rus']
    article_data_original = article_data['original']
    link = article_data_rus['link']
    filename = os.path.join(folder, re.sub('[/:.]', '_', link.split('https://')[-1].split('.html')[0]))
    filename_rus = filename + '_rus.txt'
    filename_original = filename + '_original.txt'
    filename_metadata = folder+METADATA_FILENAME
    write_article_structure_to_filename(filename_rus, article_data_rus)
    write_article_structure_to_filename(filename_original, article_data_original)
    write_article_metadata_to_filename(filename_metadata, article_data_rus, article_data_original, filename_rus, filename_original)

# Создаём строку метаданных
def write_article_structure_to_filename(filename, article_data):
    with open(filename, 'w', encoding='utf-8', newline='') as fout:
        fout.write(article_data['header_title'] + '\r\n')
        fout.write(article_data['article_text'] + '\r\n')

# очистка от повсеместной ссылки на источник оригинала в переводе
def normalize_russian_header(header):
    if header.startswith(YLE_FI_PREFIX):
        return header[len(YLE_FI_PREFIX):]
    if header.endswith(YLE_FI_SUFFIX):
        remaining_length = len(header) - len(YLE_FI_SUFFIX)
        return header[0:remaining_length - 1]
    return header


def normalize_metadata(metadata):
    return metadata.replace(DELIMITER, ' ')

# Записываем метаданные по оригинальной и переводной статье
def write_article_metadata_to_filename(filename, article_data_rus, article_data_original, filename_rus, filename_original):
    with open(filename, 'a', encoding='utf-8', newline='') as fout:
        fout.write(filename_original + DELIMITER + filename_rus + DELIMITER + normalize_metadata(article_data_original['header_title']) + DELIMITER + \
        normalize_metadata(article_data_rus['header_title']) + DELIMITER + \
        normalize_metadata(article_data_original['article_author']) + DELIMITER + \
        normalize_metadata(article_data_original['article_date']) + DELIMITER +
        normalize_metadata(article_data_rus['article_date']) + DELIMITER + \
        normalize_metadata(article_data_original['link']) + DELIMITER + normalize_metadata(article_data_rus['link']) + '\r\n')

# Является ли статья финноязычной
def is_good_link(article_link, paper_name):
    return article_link is not None and article_link.startswith(PAPER_ORIGINAL_LINKS_PREFIX[paper_name])

# Является ли текст выносным абзацем "Контекст"
def is_aside_paragraph(p):
    return p.find('aside') is not None

def parse_inosmi_article_page(all_articles_url, paper_name):
    print('parsing ' + all_articles_url)
    # Получаем ссылки на все статьи и на следующую страницу каталога
    article_links, next_url = get_article_links(all_articles_url)
    bad_links = []
    # Парсим каждую статью
    num_good = 0
    for article_link in article_links:
        article_data = parse_article(article_link, paper_name)
        # Если удалось распарсить, записываем в файл
        if article_data['is_good'] and article_data.get('original') is not None\
            and article_data.get('original').get('is_good'):
            # Записываем в файл
            write_article_to_file(article_data, paper_name)
            num_good += 1
        else:
            bad_links.append(article_link)
    print('sucessfully parsed ' + str(num_good) + ' articles for ' + all_articles_url)
    if bad_links:
        print('bad articles: ' + ','.join(bad_links))
    return next_url


def parse_inosmi_paper(paper_name):
# Пишем в csv названия колонок метаданных
    with open(paper_name+METADATA_FILENAME, 'w', encoding='utf-8', newline='') as fout:
        fout.write('original filename' + DELIMITER + 'rus filename' + DELIMITER + 'original title' + DELIMITER + 'rus title' + DELIMITER + \
        'original author' + DELIMITER + 'original date' + DELIMITER + 'rus date' + DELIMITER + 'original link' + DELIMITER + 'rus link'  + '\r\n')
    # Создаём папку для сохранения txt, еслт её ещё нет
    if not os.path.exists(paper_name):
        os.makedirs(paper_name)
    # Попадаем на страницу обрабатываемой газеты
    next_url =  URL + '/' + paper_name
    # Нажатие кнопки "загрузить ещё" внизу открывшегося списка каталога
    while next_url:
        next_url = parse_inosmi_article_page(next_url, paper_name)
        print('NEXT_URL', next_url)
        # Пауза, чтобы не забрасывать сайт запросами
        time.sleep(PAUSE_SEC)

# Основная функция, обрабатывает газету Yle из каталога Иносми
parse_inosmi_paper('yle_fi')
