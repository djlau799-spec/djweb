import type React from 'react';
import { useState } from 'react';
import { Bell, Trash2 } from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, EmptyState, Pagination, Select } from '../common';
import type { AlertRuleItem, AlertType } from '../../types/alerts';
import { formatDateTime } from '../../utils/format';

export type AlertRuleEnabledFilter = 'all' | 'enabled' | 'disabled';
export type AlertTypeFilter = 'all' | AlertType;
export type AlertRuleBusyAction = 'test' | 'toggle' | 'delete';

export interface AlertRuleBusyState {
  id: number;
  action: AlertRuleBusyAction;
}

const ENABLED_FILTER_OPTIONS = [
  { value: 'all', label: 'AllStatus' },
  { value: 'enabled', label: 'Enabled' },
  { value: 'disabled', label: 'Disabled' },
];

const ALERT_TYPE_FILTER_OPTIONS = [
  { value: 'all', label: 'AllType' },
  { value: 'price_cross', label: 'Price breakout' },
  { value: 'price_change_percent', label: 'Change %' },
  { value: 'volume_spike', label: 'Volume spike' },
  { value: 'ma_price_cross', label: 'Price/MA cross' },
  { value: 'rsi_threshold', label: 'RSI Threshold' },
  { value: 'macd_cross', label: 'MACD Bullish cross/Bearish cross' },
  { value: 'kdj_cross', label: 'KDJ Bullish cross/Bearish cross' },
  { value: 'cci_threshold', label: 'CCI Threshold' },
  { value: 'portfolio_stop_loss', label: 'Portfolio stop-loss' },
  { value: 'portfolio_concentration', label: 'Portfolio concentration' },
  { value: 'portfolio_drawdown', label: 'Portfolio drawdown' },
  { value: 'portfolio_price_stale', label: 'Portfolio price status' },
  { value: 'market_light_status', label: 'Market traffic-light status' },
  { value: 'market_light_score_drop', label: 'Market traffic-light score drop' },
];

const typeLabel: Record<AlertType, string> = {
  price_cross: 'Price breakout',
  price_change_percent: 'Change %',
  volume_spike: 'Volume spike',
  ma_price_cross: 'Price/MA cross',
  rsi_threshold: 'RSI Threshold',
  macd_cross: 'MACD Bullish cross/Bearish cross',
  kdj_cross: 'KDJ Bullish cross/Bearish cross',
  cci_threshold: 'CCI Threshold',
  portfolio_stop_loss: 'Portfolio stop-loss',
  portfolio_concentration: 'Portfolio concentration',
  portfolio_drawdown: 'Portfolio drawdown',
  portfolio_price_stale: 'Portfolio price status',
  market_light_status: 'Market traffic-light status',
  market_light_score_drop: 'Market traffic-light score drop',
};

const severityLabel: Record<string, string> = {
  info: 'Info',
  warning: 'Warning',
  critical: 'Critical',
};

const scopeLabel: Record<string, string> = {
  single_symbol: 'Single symbol',
  watchlist: 'Watchlist',
  portfolio_holdings: 'Portfolio holdings',
  portfolio_account: 'Portfolio account',
  market: 'Market',
};

const marketRegionLabel: Record<string, string> = {
  cn: 'A-shares',
  hk: 'Hong Kong stocks',
  us: 'US stocks',
};

const marketLightStatusLabel: Record<string, string> = {
  yellow: 'Yellow',
  red: 'Red',
};

function formatParameters(rule: AlertRuleItem): string {
  if (rule.alertType === 'market_light_status') {
    const statuses = rule.parameters.statuses ?? [];
    return statuses.length > 0
      ? statuses.map((status) => marketLightStatusLabel[status] ?? status).join(' / ')
      : '--';
  }
  if (rule.alertType === 'market_light_score_drop') {
    return `Score drop >= ${rule.parameters.minDrop ?? '--'}`;
  }
  if (rule.alertType === 'price_cross') {
    return `${rule.parameters.direction === 'below' ? 'Break below' : 'Break above'} ${rule.parameters.price ?? '--'}`;
  }
  if (rule.alertType === 'price_change_percent') {
    return `${rule.parameters.direction === 'down' ? 'Down' : 'Up'} ${rule.parameters.changePct ?? '--'}%`;
  }
  if (rule.alertType === 'volume_spike') {
    return `${rule.parameters.multiplier ?? '--'}x`;
  }
  if (rule.alertType === 'ma_price_cross') {
    return `${rule.parameters.direction === 'below' ? 'Cross below' : 'Cross above'} MA${rule.parameters.window ?? '--'}`;
  }
  if (rule.alertType === 'rsi_threshold') {
    return `RSI${rule.parameters.period ?? '--'} ${rule.parameters.direction === 'below' ? 'Cross below' : 'Cross above'} ${rule.parameters.threshold ?? '--'}`;
  }
  if (rule.alertType === 'macd_cross' || rule.alertType === 'kdj_cross') {
    const direction = rule.parameters.direction === 'bearish_cross' ? 'Bearish cross' : 'Bullish cross';
    if (rule.alertType === 'macd_cross') {
      return `MACD(${rule.parameters.fastPeriod ?? '--'},${rule.parameters.slowPeriod ?? '--'},${rule.parameters.signalPeriod ?? '--'}) ${direction}`;
    }
    return `KDJ(${rule.parameters.period ?? '--'},${rule.parameters.kPeriod ?? '--'},${rule.parameters.dPeriod ?? '--'}) ${direction}`;
  }
  if (rule.alertType === 'portfolio_stop_loss') {
    return rule.parameters.mode === 'breach' ? 'Stop-loss triggered' : 'Near stop-loss';
  }
  if (rule.alertType === 'portfolio_concentration') return 'top_weight_pct';
  if (rule.alertType === 'portfolio_drawdown') return 'max_drawdown_pct';
  if (rule.alertType === 'portfolio_price_stale') return 'price_stale / price_available';
  return `CCI${rule.parameters.period ?? '--'} ${rule.parameters.direction === 'below' ? 'Cross below' : 'Cross above'} ${rule.parameters.threshold ?? '--'}`;
}

function isCoolingDown(rule: AlertRuleItem): boolean {
  return rule.cooldownActive === true;
}

function formatTarget(rule: AlertRuleItem): string {
  if (rule.targetScope === 'market') return marketRegionLabel[rule.target] ?? rule.target;
  if (rule.targetScope === 'watchlist') return 'default';
  if (rule.targetScope === 'portfolio_account' || rule.targetScope === 'portfolio_holdings') {
    return rule.target === 'all' ? 'AllAccount' : `Account ${rule.target}`;
  }
  return rule.target;
}

function hasChildTargetCooldown(rule: AlertRuleItem): boolean {
  return rule.targetScope === 'watchlist' || rule.targetScope === 'portfolio_holdings';
}

interface AlertRuleListProps {
  rules: AlertRuleItem[];
  total: number;
  page: number;
  pageSize: number;
  className?: string;
  isLoading?: boolean;
  enabledFilter: AlertRuleEnabledFilter;
  alertTypeFilter: AlertTypeFilter;
  onEnabledFilterChange: (value: AlertRuleEnabledFilter) => void;
  onAlertTypeFilterChange: (value: AlertTypeFilter) => void;
  onPageChange: (page: number) => void;
  onToggleEnabled: (rule: AlertRuleItem) => void;
  onDelete: (rule: AlertRuleItem) => void;
  onTest: (rule: AlertRuleItem) => void;
  busyRule?: AlertRuleBusyState | null;
}

export const AlertRuleList: React.FC<AlertRuleListProps> = ({
  rules,
  total,
  page,
  pageSize,
  className,
  isLoading = false,
  enabledFilter,
  alertTypeFilter,
  onEnabledFilterChange,
  onAlertTypeFilterChange,
  onPageChange,
  onToggleEnabled,
  onDelete,
  onTest,
  busyRule = null,
}) => {
  const [pendingDelete, setPendingDelete] = useState<AlertRuleItem | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const isRuleBusy = (rule: AlertRuleItem) => busyRule?.id === rule.id;
  const isRuleActionBusy = (rule: AlertRuleItem, action: AlertRuleBusyAction) => (
    busyRule?.id === rule.id && busyRule.action === action
  );

  return (
    <Card title="Alert rules" subtitle={`${total} rules`} variant="bordered" padding="md" className={className}>
      <div className="mb-4 grid gap-3 md:grid-cols-2">
        <Select
          label="Enabled status"
          value={enabledFilter}
          options={ENABLED_FILTER_OPTIONS}
          onChange={(value) => {
            onEnabledFilterChange(value as AlertRuleEnabledFilter);
          }}
        />
        <Select
          label="Rule type"
          value={alertTypeFilter}
          options={ALERT_TYPE_FILTER_OPTIONS}
          onChange={(value) => {
            onAlertTypeFilterChange(value as AlertTypeFilter);
          }}
        />
      </div>

      {rules.length === 0 ? (
        <div className="flex min-h-[220px] flex-1 items-center justify-center">
          <EmptyState
            icon={<Bell className="h-6 w-6" />}
            title={isLoading ? 'Loading rules' : 'NoneAlert rules'}
            description="After a rule is created, the background evaluator processes enabled alerts on its polling cycle."
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-x-auto">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
              <tr>
                <th className="px-3 py-2 font-medium">Rule</th>
                <th className="px-3 py-2 font-medium">Target</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Parameters</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Cooldown</th>
                <th className="px-3 py-2 font-medium">UpdateTime</th>
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {rules.map((rule) => (
                <tr key={rule.id} className="align-top">
                  <td className="px-3 py-3">
                    <div className="font-medium text-foreground">{rule.name}</div>
                    <div className="mt-1 text-xs text-muted-text">Source：{rule.source}</div>
                  </td>
                  <td className="px-3 py-3 text-secondary-text">
                    <div className="font-mono">{formatTarget(rule)}</div>
                    <div className="mt-1 text-xs">{scopeLabel[rule.targetScope] ?? rule.targetScope}</div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-col items-start gap-1">
                      <Badge variant="info">{typeLabel[rule.alertType]}</Badge>
                      <Badge variant={rule.severity === 'critical' ? 'danger' : rule.severity === 'warning' ? 'warning' : 'default'}>
                        {severityLabel[rule.severity] ?? rule.severity}
                      </Badge>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-secondary-text">{formatParameters(rule)}</td>
                  <td className="px-3 py-3">
                    <Badge variant={rule.enabled ? 'success' : 'default'}>
                      {rule.enabled ? 'Enabled' : 'Disabled'}
                    </Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-secondary-text">
                    <div>{isCoolingDown(rule) ? 'Cooling down' : 'Not cooling down'}</div>
                    <div className="mt-1">{formatDateTime(rule.cooldownUntil)}</div>
                    {hasChildTargetCooldown(rule) ? (
                      <div className="mt-1 text-muted-text">See trigger history for child targets</div>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-xs text-secondary-text">{formatDateTime(rule.updatedAt ?? rule.createdAt)}</td>
                  <td className="px-3 py-3">
                    <div className="flex justify-end gap-2">
                      <Button
                        size="xsm"
                        variant="outline"
                        onClick={() => onTest(rule)}
                        isLoading={isRuleActionBusy(rule, 'test')}
                        loadingText="Testing"
                        disabled={isRuleBusy(rule) && !isRuleActionBusy(rule, 'test')}
                      >
                        Test
                      </Button>
                      <Button
                        size="xsm"
                        variant={rule.enabled ? 'secondary' : 'primary'}
                        onClick={() => onToggleEnabled(rule)}
                        isLoading={isRuleActionBusy(rule, 'toggle')}
                        loadingText={rule.enabled ? 'Disabling' : 'Enabling'}
                        disabled={isRuleBusy(rule) && !isRuleActionBusy(rule, 'toggle')}
                      >
                        {rule.enabled ? 'Disable' : 'Enable'}
                      </Button>
                      <Button
                        size="xsm"
                        variant="danger-subtle"
                        aria-label={`Delete ${rule.name}`}
                        onClick={() => setPendingDelete(rule)}
                        disabled={isRuleBusy(rule)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination
        currentPage={page}
        totalPages={totalPages}
        onPageChange={onPageChange}
        className="mt-5"
      />

      <ConfirmDialog
        isOpen={pendingDelete != null}
        title="DeleteAlert rules"
        message={pendingDelete ? `Confirm delete "${pendingDelete.name}"? This action will not delete existing trigger history.` : ''}
        confirmText="Delete"
        cancelText="Cancel"
        isDanger
        onConfirm={() => {
          if (pendingDelete) {
            onDelete(pendingDelete);
          }
          setPendingDelete(null);
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </Card>
  );
};
