// Patent Research Agent - Frontend JavaScript

// DOM elements
const patentInput = document.getElementById('patentNumbers');
const researchBtn = document.getElementById('researchBtn');
const loadingDiv = document.getElementById('loading');
const resultsDiv = document.getElementById('results');
const errorDiv = document.getElementById('error');
const progressInfo = document.getElementById('progressInfo');
const resultsTableBody = document.getElementById('resultsTableBody');
const exportBtn = document.getElementById('exportBtn');

// Global state
let tableData = [];
let eventSource = null;

// Handle Enter key press
function handleKeyPress(event) {
    if (event.key === 'Enter' && event.ctrlKey) {
        researchPatents();
    }
}

// Main research function for multiple patents
async function researchPatents() {
    const patentNumbersText = patentInput.value.trim();
    
    if (!patentNumbersText) {
        showError('Please enter patent numbers');
        return;
    }
    
    // Parse patent numbers
    const patentNumbers = patentNumbersText
        .split(',')
        .map(p => p.trim())
        .filter(p => p.length > 0);
    
    if (patentNumbers.length === 0) {
        showError('Please enter at least one valid patent number');
        return;
    }
    
    // Show loading state
    setLoadingState(true);
    hideResults();
    hideError();
    
    // Initialize table
    initializeTable(patentNumbers);
    
    try {
        // Start SSE connection
        await startSSEConnection(patentNumbers);
        
    } catch (error) {
        console.error('Error:', error);
        showError(`Failed to research patents: ${error.message}`);
        setLoadingState(false);
    }
}

// Initialize table with pending rows
function initializeTable(patentNumbers) {
    resultsTableBody.innerHTML = '';
    tableData = [];
    
    patentNumbers.forEach((patentNumber, index) => {
        const row = document.createElement('tr');
        row.className = 'pending';
        row.id = `row-${index}`;
        
        row.innerHTML = `
            <td>${patentNumber}</td>
            <td>Processing...</td>
            <td>Processing...</td>
            <td>Processing...</td>
            <td><span class="status-badge pending">Pending</span></td>
            <td>
                <button class="action-btn" disabled>Analyze</button>
            </td>
        `;
        
        resultsTableBody.appendChild(row);
        
        // Add to table data
        tableData.push({
            patent_number: patentNumber,
            inventors: '',
            publication_date: '',
            description: '',
            status: 'pending',
            index: index
        });
    });
    
    // Show results container
    resultsDiv.classList.remove('hidden');
    resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Start Server-Sent Events connection
async function startSSEConnection(patentNumbers) {
    // Close existing connection if any
    if (eventSource) {
        eventSource.close();
    }
    
    const response = await fetch('/research-multiple', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ patent_numbers: patentNumbers })
    });
    
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    // Create EventSource-like behavior with fetch
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        await handleSSEMessage(data);
                    } catch (e) {
                        console.error('Error parsing SSE message:', e);
                    }
                }
            }
        }
    } finally {
        reader.releaseLock();
        setLoadingState(false);
    }
}

// Handle SSE messages
async function handleSSEMessage(data) {
    switch (data.type) {
        case 'status':
            updateProgress(data);
            break;
        case 'complete':
            await updateTableRow(data);
            break;
        case 'error':
            updateTableRowError(data);
            break;
        case 'finished':
            handleProcessingComplete(data);
            break;
    }
}

// Update progress information
function updateProgress(data) {
    progressInfo.textContent = `Processing ${data.patent}... (${data.index + 1}/${tableData.length})`;
}

// Update table row with completed data
async function updateTableRow(data) {
    const row = document.getElementById(`row-${data.index}`);
    if (!row) return;
    
    const rowData = data.data;
    
    // Check if there are valid inventors for analysis
    const inventorsList = rowData.inventors.split(',').map(i => i.trim()).filter(i => i);
    const validInventors = inventorsList.filter(inventor => {
        const name = inventor.toLowerCase();
        // Filter out "et al." and similar
        if (name.includes('et al') || name.includes('and others') || name.includes('others')) {
            console.log('Filtered out:', inventor); // Debug log
            return false;
        }
        // Allow any name that's not empty and not just whitespace
        const isValid = inventor.trim().length > 0;
        if (!isValid) {
            console.log('Invalid name format:', inventor); // Debug log
        }
        return isValid;
    });
    
    const hasValidInventors = validInventors.length > 0;
    
    // Check if AI analysis is cached
    let hasCachedAnalysis = false;
    if (hasValidInventors) {
        try {
            const cacheResponse = await fetch(`/check-ai-cache/${rowData.patent_number}`);
            if (cacheResponse.ok) {
                const cacheData = await cacheResponse.json();
                hasCachedAnalysis = cacheData.has_cached_analysis;
            }
        } catch (error) {
            console.warn('Error checking AI cache:', error);
        }
    }
    
    // Update row content
    row.className = 'completed';
    row.innerHTML = `
        <td>${rowData.patent_number}</td>
        <td>${rowData.inventors || 'No inventors found'}</td>
        <td>${rowData.publication_date}</td>
        <td>${rowData.description}</td>
        <td><span class="status-badge completed">Completed</span></td>
        <td>
            <button class="action-btn" ${!hasValidInventors ? 'disabled' : ''} onclick="analyzeInventor('${rowData.patent_number}', '${rowData.description}', ${data.index})">
                ${!hasValidInventors ? 'No valid inventors' : (hasCachedAnalysis ? '📋 Show AI Analysis' : '🤖 Analyze')}
            </button>
        </td>
    `;
    
    // Update table data
    tableData[data.index] = {
        ...rowData,
        status: 'completed',
        processing_time: data.processing_time,
        hasCachedAnalysis: hasCachedAnalysis,
        hasValidInventors: hasValidInventors
    };
    
    // Update progress
    const completedCount = tableData.filter(item => item.status === 'completed').length;
    progressInfo.textContent = `Completed ${completedCount}/${tableData.length} patents`;
}

// Update table row with error
function updateTableRowError(data) {
    const row = document.getElementById(`row-${data.index}`);
    if (!row) return;
    
    const rowData = data.data;
    
    // Update row content
    row.className = 'error';
    row.innerHTML = `
        <td>${rowData.patent_number}</td>
        <td>Error</td>
        <td>Error</td>
        <td>${rowData.description}</td>
        <td><span class="status-badge error">Error</span></td>
        <td>
            <button class="action-btn" disabled>Analyze</button>
        </td>
    `;
    
    // Update table data
    tableData[data.index] = {
        ...rowData,
        status: 'error'
    };
}

// Handle processing completion
function handleProcessingComplete(data) {
    progressInfo.textContent = `Completed processing ${data.total} patents`;
    exportBtn.disabled = false;
    
    // Hide AI analysis container if no completed patents
    const completedCount = tableData.filter(item => item.status === 'completed').length;
    if (completedCount === 0) {
        document.getElementById('aiAnalysisContainer').classList.add('hidden');
    }
    
    // Refresh button states after all processing is complete
    setTimeout(() => {
        refreshButtonStates();
    }, 1000);
}

// Analyze single inventor
async function analyzeInventor(patentNumber, patentTitle, rowIndex) {
    const row = document.getElementById(`row-${rowIndex}`);
    if (!row) return;
    
    // Clear previous analysis results to show only the current one
    const aiAnalysisContent = document.getElementById('aiAnalysisContent');
    aiAnalysisContent.innerHTML = '';
    
    // Get inventors from the row
    const inventorsCell = row.cells[1];
    const inventorsText = inventorsCell.textContent;
    
    console.log('Original inventors text:', inventorsText); // Debug log
    
    if (!inventorsText || inventorsText === 'Processing...' || inventorsText === 'Error') {
        showError('No inventors found for this patent');
        return;
    }
    
    // Split inventors and filter out non-person names
    const allInventors = inventorsText.split(',').map(i => i.trim()).filter(i => i);
    console.log('All inventors after split:', allInventors); // Debug log
    
    const validInventors = allInventors.filter(inventor => {
        const name = inventor.toLowerCase();
        // Filter out "et al." and similar
        if (name.includes('et al') || name.includes('and others') || name.includes('others')) {
            console.log('Filtered out:', inventor); // Debug log
            return false;
        }
        // Allow any name that's not empty and not just whitespace
        const isValid = inventor.trim().length > 0;
        if (!isValid) {
            console.log('Invalid name format:', inventor); // Debug log
        }
        return isValid;
    });
    
    console.log('Valid inventors after filtering:', validInventors); // Debug log
    
    if (validInventors.length === 0) {
        showError(`No valid inventor names found for analysis. Original list: "${inventorsText}". Filtered out "et al." and names with less than 2 words.`);
        return;
    }
    
    // Update button to show analyzing state
    const analyzeBtn = row.querySelector('.action-btn');
    const originalText = analyzeBtn.textContent;
    analyzeBtn.textContent = 'Analyzing...';
    analyzeBtn.className = 'action-btn analyzing';
    analyzeBtn.disabled = true;
    
    try {
        const analysisResults = [];
        const errors = [];
        
        for (const inventorName of validInventors) {
            try {
                const response = await fetch('/analyze-inventor', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ patent_number: patentNumber, patent_title: patentTitle, inventor_name: inventorName })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    if (result.data && result.data.name) {
                        displayAiAnalysis(result.data, patentNumber);
                    } else {
                        console.error("Failed to display AI analysis: response data is incomplete.", result);
                        showError(`Analysis for ${inventorName} succeeded, but the returned data was incomplete.`);
                    }
                } else {
                    showError(`Failed to analyze ${inventorName}: ${result.detail || 'Unknown error'}`);
                }
            } catch (error) {
                errors.push(`${inventorName}: ${error.message}`);
            }
        }
        
        // Display analysis results if any
        if (analysisResults.length > 0) {
            displayAiAnalysis(analysisResults, patentNumber);
        }
        
        // Show errors if any
        if (errors.length > 0) {
            const errorMessage = `Some inventors could not be analyzed:\n${errors.join('\n')}`;
            console.warn(errorMessage);
            // Don't show error to user if we have some successful results
            if (analysisResults.length === 0) {
                showError(errorMessage);
            }
        }
        
        // Update button
        if (analysisResults.length > 0) {
            analyzeBtn.textContent = '✅ Analyzed';
            analyzeBtn.className = 'action-btn';
            analyzeBtn.disabled = true;
        } else {
            analyzeBtn.textContent = originalText;
            analyzeBtn.className = 'action-btn';
            analyzeBtn.disabled = false;
        }
        
    } catch (error) {
        console.error('Error analyzing inventor:', error);
        showError(`Failed to analyze inventors: ${error.message}`);
        
        // Reset button
        analyzeBtn.textContent = originalText;
        analyzeBtn.className = 'action-btn';
        analyzeBtn.disabled = false;
    }
}

// Display AI contact analysis
function displayAiAnalysis(analysisData, patentNumber) {
    // Gracefully handle cases where analysis data or name is missing
    if (!analysisData || !analysisData.name) {
        console.error("Failed to display AI analysis: data is incomplete.", analysisData);
        alert("Could not display AI analysis because the returned data was incomplete.");
        return;
    }

    const inventorName = analysisData.name;
    const cardId = `analysis-card-${inventorName.replace(/\s+/g, '-')}-${patentNumber}`;
    
    // Remove existing card for this inventor if it exists
    const existingCard = document.getElementById(cardId);
    if (existingCard) {
        existingCard.remove();
    }

    const aiAnalysisContainer = document.getElementById('aiAnalysisContainer');
    const aiAnalysisContent = document.getElementById('aiAnalysisContent');

    // Create a new analysis card
    const card = document.createElement('div');
    card.className = 'analysis-card';
    card.id = cardId;

    const confidenceScore = (analysisData.confidence_score * 100).toFixed(0);
    const confidenceClass = getConfidenceClass(analysisData.confidence_score);

    // --- New: LinkedIn Profile Display ---
    let linkedinHtml = `
        <div class="analysis-item">
            <strong>LinkedIn Profile:</strong>
            <p>Not found</p>
        </div>
    `;
    if (analysisData.linkedin_url) {
        linkedinHtml = `
            <div class="analysis-item">
                <strong>LinkedIn Profile:</strong>
                <p><a href="${analysisData.linkedin_url}" target="_blank">${analysisData.linkedin_url}</a></p>
            </div>
        `;
    }
    // --- End of LinkedIn Profile Display ---

    // --- Email Suggestions ---
    let emailHtml;
    if (analysisData.email_suggestions && analysisData.email_suggestions.length > 0) {
        emailHtml = `
            <div class="analysis-item">
                <strong>Email Suggestions:</strong>
                <ul class="email-suggestions">
                    ${analysisData.email_suggestions.map(email => `<li>${email} <button class="copy-btn" onclick="copyToClipboard('${email}')">📋</button></li>`).join('')}
                </ul>
            </div>
        `;
    } else {
        emailHtml = `
            <div class="analysis-item">
                <strong>Email Suggestions:</strong>
                <p>To Be Done</p>
            </div>
        `;
    }

    // --- GitHub Search Terms ---
    let githubHtml;
    if (analysisData.github_search_terms && analysisData.github_search_terms.length > 0) {
        githubHtml = `
            <div class="analysis-item">
                <strong>GitHub Search Terms:</strong>
                <p>${analysisData.github_search_terms.join(', ')}</p>
            </div>
        `;
    } else {
        githubHtml = `
            <div class="analysis-item">
                <strong>GitHub Search Terms:</strong>
                <p>To Be Done</p>
            </div>
        `;
    }

    card.innerHTML = `
        <div class="analysis-card-header">
            <h4>${analysisData.name}</h4>
            <div class="confidence-badge ${confidenceClass}">
                Confidence: ${confidenceScore}%
            </div>
        </div>
        <div class="analysis-card-body">
            <div class="analysis-item">
                <strong>Search Strategy:</strong>
                <p>${analysisData.search_strategy}</p>
            </div>
            ${linkedinHtml} 
            ${emailHtml}
            ${githubHtml}
        </div>
    `;

    // Add or replace the card in the container
    aiAnalysisContent.appendChild(card);

    aiAnalysisContainer.classList.remove('hidden');
    aiAnalysisContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    // Ensure the content area is visible if it was collapsed
    if (!aiAnalysisContent.classList.contains('active')) {
        aiAnalysisContent.classList.add('active');
        aiAnalysisContent.style.maxHeight = aiAnalysisContent.scrollHeight + "px";
        document.querySelector('#aiAnalysisHeader .collapse-icon').textContent = '[-]';
    }
}

// Export to Excel
async function exportToExcel() {
    try {
        // Filter out pending and error rows
        const exportData = tableData.filter(item => item.status === 'completed');
        
        if (exportData.length === 0) {
            showError('No completed data to export');
            return;
        }
        
        const response = await fetch('/export-excel', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ table_data: exportData })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // Download the file
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'patent_data.xlsx';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
    } catch (error) {
        console.error('Error exporting to Excel:', error);
        showError(`Failed to export: ${error.message}`);
    }
}

// Get confidence badge class
function getConfidenceClass(score) {
    if (score >= 0.8) return '';
    if (score >= 0.6) return 'medium';
    return 'low';
}

// Set loading state
function setLoadingState(isLoading) {
    const btnText = document.querySelector('.btn-text');
    const btnLoading = document.querySelector('.btn-loading');
    
    if (isLoading) {
        researchBtn.disabled = true;
        btnText.classList.add('hidden');
        btnLoading.classList.remove('hidden');
        loadingDiv.classList.remove('hidden');
    } else {
        researchBtn.disabled = false;
        btnText.classList.remove('hidden');
        btnLoading.classList.add('hidden');
        loadingDiv.classList.add('hidden');
    }
}

// Hide results
function hideResults() {
    resultsDiv.classList.add('hidden');
}

// Show error
function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    errorDiv.classList.remove('hidden');
    errorDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Hide error
function hideError() {
    errorDiv.classList.add('hidden');
}

// Copy to clipboard utility
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        console.log(`Copied "${text}" to clipboard.`);
        // Optional: show a temporary notification
        const notification = document.createElement('div');
        notification.className = 'clipboard-notification';
        notification.textContent = 'Copied!';
        document.body.appendChild(notification);
        setTimeout(() => {
            notification.remove();
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
    });
}

// Add click handlers to example patent links
function addExamplePatentHandlers() {
    const exampleLinks = document.querySelectorAll('.example-patent');
    exampleLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const patentNumbers = e.target.dataset.patents;
            if (patentNumbers) {
                patentInput.value = patentNumbers;
                researchPatents();
            }
        });
    });
}

// Initialize the page
document.addEventListener('DOMContentLoaded', function() {
    // Focus on input
    patentInput.focus();
    
    // Add example patent functionality
    addExamplePatentHandlers();

    // Add collapsible functionality for AI Analysis section
    const collapsible = document.getElementById('aiAnalysisHeader');
    if (collapsible) {
        collapsible.addEventListener('click', function() {
            this.classList.toggle('active');
            const content = this.nextElementSibling;
            const icon = this.querySelector('.collapse-icon');
            if (content.style.maxHeight) {
                content.style.maxHeight = null;
                icon.textContent = '[+]';
            } else {
                content.style.maxHeight = content.scrollHeight + "px";
                icon.textContent = '[-]';
            }
        });
    }
    
    // Add some helpful tips
    console.log('Patent Research Agent loaded!');
    console.log('Try these test batches: Small Batch (3), Medium Batch (4), Large Batch (4)');
});

// Add some CSS for the clipboard notification
const notificationStyle = document.createElement('style');
notificationStyle.textContent = `
    .clipboard-notification {
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        background-color: #333;
        color: white;
        padding: 10px 20px;
        border-radius: 5px;
        z-index: 1000;
        opacity: 0;
        transition: opacity 0.5s ease;
    }
    .clipboard-notification { opacity: 1; }
`;
document.head.appendChild(notificationStyle);

// Function to refresh button states for all completed rows
async function refreshButtonStates() {
    for (let i = 0; i < tableData.length; i++) {
        const rowData = tableData[i];
        if (rowData && rowData.status === 'completed') {
            const row = document.getElementById(`row-${i}`);
            if (row) {
                const button = row.querySelector('.action-btn');
                if (button && !button.disabled) {
                    // Re-check cache status
                    try {
                        const cacheResponse = await fetch(`/check-ai-cache/${rowData.patent_number}`);
                        if (cacheResponse.ok) {
                            const cacheData = await cacheResponse.json();
                            const hasCachedAnalysis = cacheData.has_cached_analysis;
                            button.textContent = hasCachedAnalysis ? '📋 Show AI Analysis' : '🤖 Analyze';
                            tableData[i].hasCachedAnalysis = hasCachedAnalysis;
                        }
                    } catch (error) {
                        console.warn('Error refreshing button state:', error);
                    }
                }
            }
        }
    }
} 