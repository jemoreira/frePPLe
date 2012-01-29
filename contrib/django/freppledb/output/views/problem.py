#
# Copyright (C) 2007-2012 by Johan De Taeye, frePPLe bvba
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser
# General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

# file : $URL$
# revision : $LastChangedRevision$  $LastChangedBy$
# date : $LastChangedDate$

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import string_concat
from django.db.models import Count

from freppledb.output.models import Problem
from freppledb.common.report import GridReport, GridFieldText, GridFieldNumber, GridFieldDateTime


def getEntities(request):
  return tuple([
    (i['entity'], string_concat(_(i['entity']),":",i['id__count']))
    for i in Problem.objects.using(request.database).values('entity').annotate(Count('id')).order_by('entity')
    ])


def getNames(request):
  return tuple([
    (i['name'], string_concat(_(i['name']),":",i['id__count']))
    for i in Problem.objects.using(request.database).values('name').annotate(Count('id')).order_by('name')
    ])


class Report(GridReport):
  '''
  A list report to show problems.
  '''
  template = 'output/problem.html'
  title = _("Problem Report")
  basequeryset = Problem.objects.extra(select={'forecast': "select name from forecast where out_problem.owner like forecast.name || ' - %%'",})
  model = Problem
  frozenColumns = 0
  editable = False
  rows = (
    GridFieldText('entity', title=_('entity'), editable=False, align='center'), # TODO choices=getEntities
    GridFieldText('name', title=_('name'), editable=False, align='center'),  # TODO choices=getNames
    GridFieldText('owner', title=_('owner'), editable=False),
    GridFieldText('description', title=_('description'), editable=False, width=250),
    GridFieldDateTime('startdate', title=_('start date'), editable=False),
    GridFieldDateTime('enddate', title=_('end date'), editable=False),
    GridFieldNumber('weight', title=_('weight'), editable=False),
    )
