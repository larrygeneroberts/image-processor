// Photo Analyzer JavaScript

// Lightbox functionality
function openImageModal(photoId, filename) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('modalImage');
    const modalFilename = document.getElementById('modalFilename');
    const loadingSpinner = document.getElementById('modalLoading');
    
    if (!modal || !modalImg) return;
    
    modal.style.display = 'block';
    loadingSpinner.style.display = 'block';
    modalImg.style.display = 'none';
    
    if (modalFilename) {
        modalFilename.textContent = filename || 'Photo';
    }
    
    // Load full image
    const fullImageUrl = `/photo/${photoId}/image`;
    modalImg.src = fullImageUrl;
    
    modalImg.onload = function() {
        loadingSpinner.style.display = 'none';
        modalImg.style.display = 'block';
    };
    
    modalImg.onerror = function() {
        loadingSpinner.style.display = 'none';
        modalImg.style.display = 'block';
        modalImg.src = `/photo/${photoId}/thumbnail`;
    };
}

function closeImageModal() {
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('imageModal');
    if (event.target === modal) {
        closeImageModal();
    }
}

// Close modal with ESC key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeImageModal();
    }
});

// Admin functionality
function confirmAction(message) {
    return confirm(message);
}

// Face search functionality
function searchFaces(formData) {
    fetch('/api/faces/search', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        displaySearchResults(data);
    })
    .catch(error => {
        console.error('Search error:', error);
    });
}

function displaySearchResults(results) {
    const container = document.getElementById('searchResults');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (results.length === 0) {
        container.innerHTML = '<p>No matching faces found.</p>';
        return;
    }
    
    results.forEach(result => {
        const item = document.createElement('div');
        item.className = 'search-result-item';
        item.innerHTML = `
            <img src="/photo/${result.photo_id}/thumbnail" alt="Photo">
            <div class="result-info">
                <p>Confidence: ${(result.confidence * 100).toFixed(1)}%</p>
                <a href="/photo/${result.photo_id}" class="btn">View Photo</a>
            </div>
        `;
        container.appendChild(item);
    });
}