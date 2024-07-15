#  RSS to Telegram Bot
#  Copyright (C) 2022-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
from typing import Optional
from typing_extensions import Final

import matplotlib

matplotlib.use('Agg')

from math import ceil
from PIL import Image
from io import BytesIO
from bs4 import BeautifulSoup
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontManager
from cjkwrap import fill
from warnings import filterwarnings
from cachetools import TTLCache

from ..aio_helper import run_async
from .utils import logger
from ..compat import cached_async

MPL_TTF_LIST = FontManager().ttflist
MPL_SANS_FONTS: Final = (
        list({f.name for f in MPL_TTF_LIST if f.name == 'WenQuanYi Micro Hei'})
        + list({f.name for f in MPL_TTF_LIST if f.name == 'WenQuanYi Zen Hei'})
        + list({f.name for f in MPL_TTF_LIST if f.name.startswith('Noto Sans CJK')})
        + list({f.name for f in MPL_TTF_LIST if f.name.startswith('Microsoft YaHei')})
        + list({f.name for f in MPL_TTF_LIST if f.name == 'SimHei'})
        + list({f.name for f in MPL_TTF_LIST if f.name in {'SimKai', 'SimSun', 'SimSun-ExtB'}})
        + list({f.name for f in MPL_TTF_LIST if f.name.startswith('Noto Sans') and 'cjk' not in f.name.lower()})
        + list({f.name for f in MPL_TTF_LIST if not f.name.startswith('Noto Sans') and 'sans' in f.name.lower()})
)

plt.rcParams['font.sans-serif'] = MPL_SANS_FONTS
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

filterwarnings('error', 'constrained_layout not applied', UserWarning)
filterwarnings('ignore', "coroutine 'convert_table_to_png' was never awaited", RuntimeWarning)

fig, ax = plt.subplots(figsize=(8, 8))


def _convert_table_to_png(table_html: str) -> Optional[bytes]:
    soup = BeautifulSoup(table_html, 'lxml')
    table = soup.find('table')
    if not table:
        return None
    wrap_length = 85
    column_labels: list[str] = []
    row_labels: list[str] = []
    cell_texts: list[list[str]] = []
    thead = table.find('thead')
    try:
        if thead:
            column_labels = [label.text for label in thead.find_all('th')]
            thead.decompose()
        else:
            maybe_thead = table.find('tr')
            if maybe_thead:
                ths = maybe_thead.find_all('th')
                if len(ths) > 1:
                    column_labels = [label.text for label in ths]
                    maybe_thead.decompose()
        rows = table.find_all('tr')
        if rows:
            for ori_width in rows:
                th = ori_width.find('th')
                if th:
                    row_labels.append(th.text)
                cell_texts.append([cell.text for cell in ori_width.find_all('td')])
        if not cell_texts:
            if column_labels:
                cell_texts.append(column_labels)
                column_labels = row_labels = []
            elif row_labels:
                cell_texts = [[label] for label in row_labels]
                column_labels = row_labels = []
            else:
                return None
        # ensure row number and column number
        max_columns = max(max(len(row) for row in cell_texts), len(column_labels))
        max_rows = max(len(cell_texts), len(row_labels))
        if min(max_columns, max_rows) == 0:
            return None
        if column_labels and len(column_labels) < max_columns:
            column_labels += [''] * (max_columns - len(column_labels))
        if row_labels and len(row_labels) < max_rows:
            row_labels += [''] * (max_rows - len(row_labels))
        if len(cell_texts) < max_rows:
            cell_texts += [[''] * max_columns] * (max_rows - len(cell_texts))
        wrap_length = max(wrap_length // max_columns, 10)
        for i, row in enumerate(cell_texts):
            cell_texts[i] = [fill(cell, wrap_length) for cell in row]
        for i, label in enumerate(column_labels):
            column_labels[i] = fill(label, wrap_length)
        for i, label in enumerate(row_labels):
            row_labels[i] = fill(label, wrap_length)

        auto_set_column_width_flag = True
        for _ in range(2):
            try:
                # draw table
                table = ax.table(cellText=cell_texts,
                                 rowLabels=row_labels or None,
                                 colLabels=column_labels or None,
                                 loc='center',
                                 cellLoc='center',
                                 rowLoc='center')
                if auto_set_column_width_flag:
                    table.auto_set_column_width(tuple(range(max_columns)))
                # set row height
                cell_d = table.get_celld()
                row_range = {xy[0] for xy in cell_d}
                column_range = {xy[1] for xy in cell_d}
                row_heights = {
                    row:
                        max(cell.get_height() * (cell.get_text().get_text().count('\n') + 1) * 0.75
                            + cell.get_height() * 0.25
                            for cell in (cell_d[row, column] for column in column_range))
                    for row in row_range
                }
                for xy, cell in cell_d.items():
                    cell.set_height(row_heights[xy[0]])
                fig.set_constrained_layout(True)
                ax.axis('off')
                plt_buffer = BytesIO()
                fig.savefig(plt_buffer, format='png', dpi=200)
            except UserWarning:
                # if auto_set_column_width_flag:
                #     auto_set_column_width_flag = False  # oops, overflowed!
                #     continue  # once a figure is exported, some stuff may be frozen, so we need to re-create the table
                return None
            except Exception as e:
                raise e
            finally:
                # noinspection PyBroadException
                try:
                    plt.cla()
                except Exception:
                    pass
            # crop
            # noinspection PyUnboundLocalVariable
            image = Image.open(plt_buffer)
            ori_width, ori_height = image.size
            # trim white border
            upper = left = 0
            lower, right = ori_height - 1, ori_width - 1
            while left + 1 < ori_width and upper + 1 < ori_height and image.getpixel((left, upper))[0] >= 128:
                upper += 1
                left += 1
            while upper - 1 >= 0 and image.getpixel((left, upper - 1))[0] < 128:
                upper -= 1
            while left - 1 >= 0 and image.getpixel((left - 1, upper))[0] < 128:
                left -= 1
            while right - 1 >= 0 and lower - 1 >= 0 and image.getpixel((right, lower))[0] >= 128:
                lower -= 1
                right -= 1
            while lower + 1 < ori_height and image.getpixel((right, lower + 1))[0] < 128:
                lower += 1
            while right + 1 < ori_width and image.getpixel((right + 1, lower))[0] < 128:
                right += 1
            # add a slim border
            border_width = 15
            left = max(0, left - border_width)
            right = min(ori_width - 1, right + border_width)
            upper = max(0, upper - border_width)
            lower = min(ori_height - 1, lower + border_width)
            width, height = right - left, lower - upper
            # ensure aspect ratio
            max_aspect_ratio = 15
            if width / height > max_aspect_ratio:
                height = ceil(width / max_aspect_ratio)
                middle = int((upper + lower) / 2)
                upper = middle - height // 2
                lower = middle + height // 2
            elif height / width > max_aspect_ratio:
                width = ceil(height / max_aspect_ratio)
                middle = int((left + right) / 2)
                left = middle - width // 2
                right = middle + width // 2
            old_image = image
            image = image.crop((left, upper, right, lower))
            old_image.close()
            buffer = BytesIO()
            image.save(buffer, format='png')
            ret = buffer.getvalue()
            image.close()
            buffer.close()
            plt_buffer.close()
            return ret
    except Exception as e:
        logger.debug('Drawing table failed', exc_info=e)
        return None


@cached_async(TTLCache(maxsize=32, ttl=180))
async def convert_table_to_png(table_html: str) -> Optional[bytes]:
    return await run_async(_convert_table_to_png, table_html, prefer_pool='process')
