// Global tab switching function
function switchTab(tabId) {
    console.log('Tab switching to: ' + tabId);
    
    // Hide all tab contents
    var contents = document.getElementsByClassName('tab-content');
    for (var i = 0; i < contents.length; i++) {
        contents[i].style.display = 'none';
    }
    
    // Show the selected tab content
    var selectedContent = document.getElementById(tabId + '-content');
    if (selectedContent) {
        selectedContent.style.display = 'block';
    }
    
    // Update tab styles
    var tabs = document.querySelectorAll('[role="tab"]');
    for (var i = 0; i < tabs.length; i++) {
        tabs[i].classList.remove('active', 'text-blue-600', 'border-blue-600');
        tabs[i].classList.add('border-transparent');
    }
    
    // Activate selected tab
    var selectedTab = document.getElementById(tabId + '-tab');
    if (selectedTab) {
        selectedTab.classList.add('active', 'text-blue-600', 'border-blue-600');
        selectedTab.classList.remove('border-transparent');
    }
    
    return false;
}

// Make function available globally
window.switchTab = switchTab;
