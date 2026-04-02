#!/usr/bin/env python3
"""
Enhanced Learning Service - Recommendation-Based Intelligence
Provides insights and better approaches, never automatic decisions
"""

from learning_service import LearningService
import json
from typing import Dict, List, Any
from datetime import datetime

class EnhancedLearningService(LearningService):
    """Enhanced learning that provides intelligence, not rules"""
    
    def get_strategy_intelligence(self, carrier: str, strategy: str) -> Dict[str, Any]:
        """Get comprehensive intelligence about a strategy"""
        conn = self._get_connection()
        
        # Get success rate and outcomes
        cursor = conn.execute("""
            SELECT so.outcome, so.denial_reason, so.approved_amount, 
                   se.created_at, se.amount_requested, se.status
            FROM strategy_outcomes so
            JOIN supplement_events se ON so.supplement_event_id = se.id
            WHERE se.carrier = ? AND so.strategy_name = ?
            AND se.created_at > date('now', '-90 days')
            ORDER BY se.created_at DESC
        """, (carrier, strategy))
        
        outcomes = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        if len(outcomes) < 3:  # Not enough data
            return {
                'strategy': strategy,
                'carrier': carrier,
                'data_insufficient': True,
                'sample_size': len(outcomes),
                'recommendation': 'monitor_results'
            }
        
        # Calculate success metrics
        total = len(outcomes)
        successful = len([o for o in outcomes if o['outcome'] in ['approved', 'partial']])
        success_rate = (successful / total) * 100
        
        # Analyze denial patterns
        denials = [o for o in outcomes if o['outcome'] == 'denied']
        denial_reasons = [d['denial_reason'] for d in denials if d['denial_reason']]
        
        # Analyze successful cases  
        successes = [o for o in outcomes if o['outcome'] in ['approved', 'partial']]
        
        intelligence = {
            'strategy': strategy,
            'carrier': carrier,
            'success_rate': round(success_rate, 1),
            'sample_size': total,
            'last_updated': datetime.now().isoformat(),
            'recommendation_type': self._get_recommendation_type(success_rate),
            'insights': self._generate_strategy_insights(strategy, carrier, outcomes, denials, successes)
        }
        
        return intelligence
    
    def _get_recommendation_type(self, success_rate: float) -> str:
        """Classify recommendation type based on success rate"""
        if success_rate < 25:
            return 'needs_better_approach'
        elif success_rate > 75:
            return 'current_approach_working'  
        elif success_rate > 50:
            return 'good_approach_refine'
        else:
            return 'standard_approach_monitor'
    
    def _generate_strategy_insights(self, strategy: str, carrier: str, 
                                   outcomes: List[Dict], denials: List[Dict], 
                                   successes: List[Dict]) -> Dict[str, Any]:
        """Generate actionable insights for a strategy"""
        insights = {
            'recent_trend': self._analyze_trend(outcomes),
            'common_denial_reasons': self._analyze_denial_reasons(denials),
            'successful_patterns': self._analyze_successful_patterns(successes),
            'recommended_approaches': self._suggest_approaches(strategy, carrier, outcomes)
        }
        
        return insights
    
    def _analyze_trend(self, outcomes: List[Dict]) -> Dict[str, str]:
        """Analyze if success rate is improving or declining"""
        if len(outcomes) < 6:
            return {'trend': 'insufficient_data', 'note': 'Need more data points'}
        
        # Split into recent vs older outcomes
        mid_point = len(outcomes) // 2
        recent = outcomes[:mid_point]  # More recent (ordered DESC)
        older = outcomes[mid_point:]   # Older outcomes
        
        recent_success = len([o for o in recent if o['outcome'] in ['approved', 'partial']]) / len(recent)
        older_success = len([o for o in older if o['outcome'] in ['approved', 'partial']]) / len(older)
        
        if recent_success > older_success + 0.1:  # 10% improvement
            return {
                'trend': 'improving',
                'note': f'Success rate increased from {older_success:.1%} to {recent_success:.1%}'
            }
        elif recent_success < older_success - 0.1:  # 10% decline
            return {
                'trend': 'declining', 
                'note': f'Success rate dropped from {older_success:.1%} to {recent_success:.1%}'
            }
        else:
            return {
                'trend': 'stable',
                'note': f'Consistent ~{recent_success:.1%} success rate'
            }
    
    def _analyze_denial_reasons(self, denials: List[Dict]) -> List[Dict[str, Any]]:
        """Find most common denial reasons"""
        if not denials:
            return []
        
        reason_counts = {}
        for denial in denials:
            reason = denial.get('denial_reason', 'No reason provided')
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        # Sort by frequency
        common_reasons = []
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            common_reasons.append({
                'reason': reason,
                'frequency': count,
                'percentage': (count / len(denials)) * 100
            })
        
        return common_reasons[:3]  # Top 3 reasons
    
    def _analyze_successful_patterns(self, successes: List[Dict]) -> List[Dict[str, Any]]:
        """Identify patterns in successful outcomes"""
        if not successes:
            return []
        
        patterns = []
        
        # Analyze successful amounts
        amounts = [s['approved_amount'] for s in successes if s['approved_amount']]
        if amounts:
            avg_amount = sum(amounts) / len(amounts)
            patterns.append({
                'pattern_type': 'amount_range',
                'insight': f'Successful requests average ${avg_amount:,.0f}',
                'data': {'average': avg_amount, 'count': len(amounts)}
            })
        
        # Analyze timing patterns (if we had more context data)
        recent_successes = [s for s in successes if 'approved' in s.get('outcome', '')]
        if recent_successes:
            patterns.append({
                'pattern_type': 'recent_wins',
                'insight': f'{len(recent_successes)} recent approvals suggest approach is viable',
                'data': {'recent_approvals': len(recent_successes)}
            })
        
        return patterns
    
    def _suggest_approaches(self, strategy: str, carrier: str, outcomes: List[Dict]) -> List[Dict[str, str]]:
        """Suggest alternative approaches based on strategy and carrier"""
        approaches = []
        
        # Strategy-specific recommendations
        if strategy == 'steep_on_waste':
            approaches = [
                {
                    'approach': 'EagleView pitch documentation',
                    'description': 'Use precise measurements instead of generic steep roof claims',
                    'evidence': 'EagleView pitch diagram + safety equipment costs'
                },
                {
                    'approach': 'OSHA safety compliance angle', 
                    'description': 'Document additional safety requirements for steep installations',
                    'evidence': 'Safety equipment rental receipts + compliance documentation'
                },
                {
                    'approach': 'Time study comparison',
                    'description': 'Show actual time difference between flat vs steep installation', 
                    'evidence': 'Contractor time logs + productivity comparison'
                }
            ]
        elif strategy == 'O&P':
            approaches = [
                {
                    'approach': 'Multi-trade coordination',
                    'description': 'Emphasize coordination complexity across multiple trades',
                    'evidence': 'Project timeline + trade scheduling documentation'
                },
                {
                    'approach': 'Business overhead documentation',
                    'description': 'Provide concrete business expenses and licensing',
                    'evidence': 'Business license + office lease + employee verification'
                },
                {
                    'approach': 'Project management services',
                    'description': 'Detail specific PM activities and deliverables',
                    'evidence': 'Project management plan + progress reports'
                }
            ]
        elif strategy == 'full_fence_scope':
            approaches = [
                {
                    'approach': 'Pre-loss condition matching',
                    'description': 'Document requirement to match existing appearance',
                    'evidence': 'Before photos + building code appearance standards'
                },
                {
                    'approach': 'Partial treatment visibility',
                    'description': 'Show how partial repair creates obvious visual mismatch',
                    'evidence': 'Panoramic fence photos + close-up damage comparison'
                }
            ]
        
        # Carrier-specific adjustments
        if carrier == 'Allstate':
            for approach in approaches:
                approach['carrier_note'] = 'Allstate prefers detailed documentation - include photos and measurements'
        elif carrier == 'State_Farm':
            for approach in approaches:
                approach['carrier_note'] = 'State Farm responds well to code references and technical justifications'
        
        return approaches
    
    def get_comprehensive_intelligence(self, carrier: str, strategies: List[str]) -> Dict[str, Any]:
        """Get comprehensive intelligence for multiple strategies"""
        intelligence = {
            'carrier': carrier,
            'analysis_date': datetime.now().isoformat(),
            'strategies': {},
            'carrier_overview': self._get_carrier_overview(carrier)
        }
        
        for strategy in strategies:
            intelligence['strategies'][strategy] = self.get_strategy_intelligence(carrier, strategy)
        
        return intelligence
    
    def _get_carrier_overview(self, carrier: str) -> Dict[str, Any]:
        """Get overall carrier behavior patterns"""
        conn = self._get_connection()
        
        # Overall approval rate for this carrier
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM supplement_events 
            WHERE carrier = ? AND created_at > date('now', '-90 days')
            GROUP BY status
        """, (carrier,))
        
        status_counts = dict(cursor.fetchall())
        total = sum(status_counts.values())
        
        if total < 5:  # Not enough data
            conn.close()
            return {
                'insufficient_data': True,
                'note': f'Only {total} projects with {carrier} in last 90 days'
            }
        
        # Calculate overall success metrics
        successful = status_counts.get('approved', 0) + status_counts.get('partial', 0)
        success_rate = (successful / total) * 100
        
        conn.close()
        
        return {
            'overall_success_rate': round(success_rate, 1),
            'total_projects': total,
            'approval_breakdown': {
                'approved': status_counts.get('approved', 0),
                'partial': status_counts.get('partial', 0), 
                'denied': status_counts.get('denied', 0)
            },
            'recommendation': self._get_carrier_recommendation(success_rate)
        }
    
    def _get_carrier_recommendation(self, success_rate: float) -> str:
        """Get carrier-level recommendation"""
        if success_rate > 70:
            return 'cooperative_carrier'
        elif success_rate > 40:
            return 'standard_documentation_required'
        else:
            return 'challenging_carrier_extra_evidence_needed'
    
    def _get_connection(self):
        """Get database connection"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

# Global enhanced instance
enhanced_learning = EnhancedLearningService()