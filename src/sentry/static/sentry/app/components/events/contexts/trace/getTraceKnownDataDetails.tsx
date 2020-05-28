import React from 'react';
import styled from '@emotion/styled';
import moment from 'moment-timezone';

import {Event, Organization} from 'app/types';
import {t} from 'app/locale';
import Button from 'app/components/button';
import space from 'app/styles/space';
import EventView from 'app/utils/discover/eventView';
import {getTraceDateTimeRange} from 'app/components/events/interfaces/spans/utils';

import {TraceKnownData, TraceKnownDataType} from './types';

type Output = {
  subject: string;
  value: React.ReactNode | string | null;
};

function getUserKnownDataDetails(
  data: TraceKnownData,
  type: TraceKnownDataType,
  event: Event,
  organization: Organization
): Output | undefined {
  switch (type) {
    case TraceKnownDataType.TRACE_ID: {
      const traceId = data.trace_id || '';

      if (!traceId) {
        return undefined;
      }

      const dateCreated = moment(event.dateCreated).valueOf() / 1000;
      const pointInTime = event?.dateReceived
        ? moment(event.dateReceived).valueOf() / 1000
        : dateCreated;

      const {start, end} = getTraceDateTimeRange({start: pointInTime, end: pointInTime});

      const orgFeatures = new Set(organization.features);

      const traceEventView = EventView.fromSavedQuery({
        id: undefined,
        name: `Events with Trace ID ${traceId}`,
        fields: ['title', 'event.type', 'project', 'trace.span', 'timestamp'],
        orderby: '-timestamp',
        query: `trace:${traceId}`,
        projects: orgFeatures.has('global-views') ? [] : [Number(event.projectID)],
        version: 2,
        start,
        end,
      });
      return {
        subject: t('trace_id'),
        value: (
          <ButtonWrapper>
            <pre className="val">
              <span className="val-string">{traceId}</span>
            </pre>
            <StyledButton
              size="xsmall"
              to={traceEventView.getResultsViewUrlTarget(organization.slug)}
            >
              {t('Search by Trace')}
            </StyledButton>
          </ButtonWrapper>
        ),
      };
    }

    case TraceKnownDataType.SPAN_ID: {
      return {
        subject: t('span_id'),
        value: data.span_id || '',
      };
    }

    case TraceKnownDataType.PARENT_SPAN_ID: {
      return {
        subject: t('parent_span_id'),
        value: data.parent_span_id || '',
      };
    }

    case TraceKnownDataType.OP_NAME: {
      return {
        subject: t('op'),
        value: data.op || '',
      };
    }

    case TraceKnownDataType.STATUS: {
      return {
        subject: t('status'),
        value: data.status || '',
      };
    }

    default:
      return undefined;
  }
}

const ButtonWrapper = styled('div')`
  position: relative;
`;

const StyledButton = styled(Button)`
  position: absolute;
  top: ${space(0.75)};
  right: ${space(0.5)};
`;

export default getUserKnownDataDetails;