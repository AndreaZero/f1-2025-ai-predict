import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
import joblib
from datetime import datetime
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from data_loader import F1DataLoader

# Calendario F1 2025
F1_CALENDAR_2025 = [
    "Australian Grand Prix - Melbourne (16 Mar) - COMPLETED",
    "Chinese Grand Prix - Shanghai (23 Mar) - COMPLETED",
    "Japanese Grand Prix - Suzuka (6 Apr)",
    "Bahrain Grand Prix - Sakhir (13 Apr)",
    "Saudi Arabian Grand Prix - Jeddah (20 Apr)",
    "Miami Grand Prix - Miami (4 May)",
    "Emilia Romagna Grand Prix - Imola (18 May)",
    "Monaco Grand Prix - Monte Carlo (25 May)",
    "Spanish Grand Prix - Barcelona (1 Jun)",
    "Canadian Grand Prix - Montreal (15 Jun)",
    "Austrian Grand Prix - Spielberg (29 Jun)",
    "British Grand Prix - Silverstone (6 Jul)",
    "Belgian Grand Prix - Spa-Francorchamps (27 Jul)",
    "Hungarian Grand Prix - Budapest (3 Aug)",
    "Dutch Grand Prix - Zandvoort (31 Aug)",
    "Italian Grand Prix - Monza (7 Sep)",
    "Azerbaijan Grand Prix - Baku (21 Sep)",
    "Singapore Grand Prix - Singapore (5 Oct)",
    "United States Grand Prix - Austin (19 Oct)",
    "Mexico City Grand Prix - Mexico City (26 Oct)",
    "São Paulo Grand Prix - São Paulo (9 Nov)",
    "Las Vegas Grand Prix - Las Vegas (22 Nov)",
    "Qatar Grand Prix - Lusail (30 Nov)",
    "Abu Dhabi Grand Prix - Yas Marina (7 Dec)"
]

class F1Predictor:
    def __init__(self, data_path='f1data'):
        self.data_path = data_path
        self.model = None
        self.data_loader = F1DataLoader(data_path)
        self.feature_importance = None
        self.grid_2025 = None
        self.results_2025 = None
        self.load_2025_data()
        # Try to load existing model at initialization
        try:
            self.load_model()
        except:
            pass
    
    def load_2025_data(self):
        """Load the 2025 F1 grid and results data."""
        try:
            self.grid_2025 = pd.read_csv(f'{self.data_path}/f1_2025_grid.csv')
            self.results_2025 = pd.read_csv(f'{self.data_path}/f1_2025_results.csv')
        except Exception as e:
            print(f"Error loading 2025 data: {e}")
    
    def get_driver_recent_results(self, driver_name):
        """Get recent results for a driver in 2025."""
        if self.results_2025 is None:
            return None
        
        driver_results = self.results_2025[self.results_2025['driver_name'] == driver_name]
        return driver_results.sort_values('date', ascending=False)
    
    def predict_2025_race(self, circuit_name, qualifying_results=None):
        """
        Predict the outcome of a 2025 race.
        
        Args:
            circuit_name (str): Name of the circuit
            qualifying_results (dict): Optional dictionary with grid positions for each driver
        """
        if self.model is None or self.grid_2025 is None:
            return None
            
        # Create a prediction dataframe
        pred_df = self.grid_2025.copy()
        
        # Add default values for required features
        pred_df['grid'] = range(1, len(pred_df) + 1)  # Default grid positions
        if qualifying_results:
            for driver_id, position in qualifying_results.items():
                pred_df.loc[pred_df['driverId'] == driver_id, 'grid'] = position
        
        # Add other required features with reasonable default values
        pred_df['qual_position_avg'] = pred_df['grid']
        
        # Update points_moving_avg based on 2025 results
        pred_df['points_moving_avg'] = 0
        if self.results_2025 is not None:
            for idx, row in pred_df.iterrows():
                recent_results = self.get_driver_recent_results(row['driver_name'])
                if recent_results is not None and not recent_results.empty:
                    # Calculate points based on positions (simplified)
                    points = recent_results['position'].map(lambda x: max(26-x, 0)).mean()
                    pred_df.loc[idx, 'points_moving_avg'] = points
        
        pred_df['circuit_wins'] = 0  # Could be updated with historical data
        pred_df['points_championship'] = pred_df['points_moving_avg']
        
        # Calculate championship positions based on points
        pred_df['position_championship'] = pred_df['points_championship'].rank(ascending=False, method='min')
        
        # Calculate constructor stats
        constructor_stats = pred_df.groupby('team_name').agg({
            'points_moving_avg': ['mean', 'std']
        }).reset_index()
        constructor_stats.columns = ['team_name', 'constructor_points_mean', 'constructor_points_std']
        
        pred_df = pd.merge(pred_df, constructor_stats, on='team_name', how='left')
        pred_df['constructor_position_mean'] = pred_df['constructor_points_mean'].rank(ascending=False, method='min')
        
        # Encode categorical variables
        for col, encoder in self.data_loader.label_encoders.items():
            if col == 'nationality':
                pred_df[f'{col}_encoded'] = encoder.transform(pred_df['nationality'])
            elif col == 'nationality_constructor':
                pred_df[f'{col}_encoded'] = encoder.transform(pred_df['constructor_nationality'])
            elif col == 'country':
                # Use a default value for now
                pred_df[f'{col}_encoded'] = 0
        
        # Select features in the same order as training
        feature_columns = [
            'grid',
            'qual_position_avg',
            'points_moving_avg',
            'circuit_wins',
            'points_championship',
            'position_championship',
            'constructor_points_mean',
            'constructor_points_std',
            'constructor_position_mean',
            'nationality_encoded',
            'nationality_constructor_encoded',
            'country_encoded'
        ]
        
        # Get win probabilities for each driver
        win_probs = self.model.predict_proba(pred_df[feature_columns])[:, 1]
        
        # Create results dataframe
        results = pd.DataFrame({
            'Driver': pred_df['driver_name'],
            'Team': pred_df['team_name'],
            'Grid': pred_df['grid'],
            'Win Probability': win_probs,
            'Championship Points': pred_df['points_championship']
        })
        
        return results.sort_values('Win Probability', ascending=False).reset_index(drop=True)
    
    def train_model(self):
        # Get prepared features from data loader
        X_train, y_train, X_val, y_val, X_test, y_test = self.data_loader.prepare_features()
        
        # Initialize and train Random Forest model
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42
        )
        self.model.fit(X_train, y_train)
        
        # Calculate feature importance
        self.feature_importance = pd.DataFrame({
            'feature': X_train.columns,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        # Evaluate model
        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)
        test_pred = self.model.predict(X_test)
        
        # Calculate probabilities for ROC AUC
        train_proba = self.model.predict_proba(X_train)[:, 1]
        val_proba = self.model.predict_proba(X_val)[:, 1]
        test_proba = self.model.predict_proba(X_test)[:, 1]
        
        metrics = {
            'Train Accuracy': accuracy_score(y_train, train_pred),
            'Validation Accuracy': accuracy_score(y_val, val_pred),
            'Test Accuracy': accuracy_score(y_test, test_pred),
            'Train ROC AUC': roc_auc_score(y_train, train_proba),
            'Validation ROC AUC': roc_auc_score(y_val, val_proba),
            'Test ROC AUC': roc_auc_score(y_test, test_proba)
        }
        
        # Calculate precision, recall, and F1 score for test set
        precision, recall, f1, _ = precision_recall_fscore_support(y_test, test_pred, average='binary')
        metrics.update({
            'Test Precision': precision,
            'Test Recall': recall,
            'Test F1 Score': f1
        })
        
        return metrics
    
    def save_model(self, filename='f1_model.joblib'):
        if self.model is not None:
            model_data = {
                'model': self.model,
                'feature_importance': self.feature_importance,
                'label_encoders': self.data_loader.label_encoders
            }
            joblib.dump(model_data, filename)
            return f"Model saved to {filename}"
    
    def load_model(self, filename='f1_model.joblib'):
        model_data = joblib.load(filename)
        self.model = model_data['model']
        self.feature_importance = model_data['feature_importance']
        self.data_loader.label_encoders = model_data['label_encoders']
        return f"Model loaded from {filename}"

def main():
    st.set_page_config(
        page_title="F1 2025 Race Winner Predictor",
        page_icon="🏎️",
        layout="wide"
    )
    
    st.title('🏎️ F1 2025 Race Winner Predictor')
    st.write('Predicting Formula 1 race winners using machine learning')
    
    predictor = F1Predictor()
    
    # Sidebar
    st.sidebar.header('Model Controls')
    
    # Main content area tabs
    tab1, tab2 = st.tabs(["Model Training", "2025 Predictions"])
    
    with tab1:
        if st.button('Train New Model'):
            with st.spinner('Training model...'):
                try:
                    metrics = predictor.train_model()
                    
                    # Display metrics in main area
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.subheader('Accuracy Metrics')
                        for metric in ['Train Accuracy', 'Validation Accuracy', 'Test Accuracy']:
                            st.metric(metric, f"{metrics[metric]:.2%}")
                    
                    with col2:
                        st.subheader('ROC AUC Scores')
                        for metric in ['Train ROC AUC', 'Validation ROC AUC', 'Test ROC AUC']:
                            st.metric(metric, f"{metrics[metric]:.2%}")
                    
                    with col3:
                        st.subheader('Test Set Metrics')
                        for metric in ['Test Precision', 'Test Recall', 'Test F1 Score']:
                            st.metric(metric, f"{metrics[metric]:.2%}")
                    
                    # Feature importance plot
                    st.subheader('Feature Importance')
                    fig = px.bar(
                        predictor.feature_importance,
                        x='importance',
                        y='feature',
                        orientation='h',
                        title='Model Feature Importance'
                    )
                    fig.update_layout(
                        xaxis_title='Importance Score',
                        yaxis_title='Feature',
                        height=500
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Save the model
                    save_message = predictor.save_model()
                    st.success('Model trained and saved successfully!')
                    st.info(save_message)
                    
                except Exception as e:
                    st.error(f'Error during model training: {str(e)}')
    
    with tab2:
        if predictor.model is None:
            st.warning("Please train a model first or load an existing model.")
            if st.button("Load Existing Model"):
                try:
                    load_message = predictor.load_model()
                    st.success(load_message)
                except Exception as e:
                    st.error(f"Error loading model: {str(e)}")
        else:
            st.subheader("2025 Race Predictions")
            
            # Add circuit selection from calendar
            circuit = st.selectbox(
                "Select Circuit",
                F1_CALENDAR_2025
            )
            
            # Option to modify grid positions
            modify_grid = st.checkbox("Modify Grid Positions")
            
            qualifying_results = None
            if modify_grid:
                st.write("Enter grid positions (1-20):")
                col1, col2 = st.columns(2)
                qualifying_results = {}
                
                for idx, row in predictor.grid_2025.iterrows():
                    if idx % 2 == 0:
                        with col1:
                            pos = st.number_input(
                                f"{row['driver_name']} ({row['team_name']})",
                                min_value=1,
                                max_value=20,
                                value=idx + 1
                            )
                    else:
                        with col2:
                            pos = st.number_input(
                                f"{row['driver_name']} ({row['team_name']})",
                                min_value=1,
                                max_value=20,
                                value=idx + 1
                            )
                    qualifying_results[row['driverId']] = pos
            
            if st.button("Predict Race Results"):
                results = predictor.predict_2025_race(circuit, qualifying_results)
                
                if results is not None:
                    st.write(f"Predicted Race Results for {circuit}")
                    
                    # Create a more visually appealing results table
                    fig = go.Figure(data=[
                        go.Table(
                            header=dict(
                                values=['Position', 'Driver', 'Team', 'Grid', 'Win Probability', 'Championship Points'],
                                fill_color='darkblue',
                                align='left',
                                font=dict(color='white', size=12)
                            ),
                            cells=dict(
                                values=[
                                    list(range(1, len(results) + 1)),  # Convert range to list
                                    results['Driver'],
                                    results['Team'],
                                    results['Grid'],
                                    [f"{x:.1%}" for x in results['Win Probability']],
                                    results['Championship Points']
                                ],
                                align='left',
                                font=dict(size=11),
                                height=30
                            )
                        )
                    ])
                    
                    fig.update_layout(
                        margin=dict(l=0, r=0, t=0, b=0),
                        height=600
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Add a bar chart of win probabilities
                    prob_fig = px.bar(
                        results.head(10),
                        x='Driver',
                        y='Win Probability',
                        title='Top 10 Drivers - Win Probability',
                        text=[f"{x:.1%}" for x in results.head(10)['Win Probability']]
                    )
                    prob_fig.update_traces(textposition='outside')
                    prob_fig.update_layout(height=400)
                    st.plotly_chart(prob_fig, use_container_width=True)

if __name__ == "__main__":
    main()
