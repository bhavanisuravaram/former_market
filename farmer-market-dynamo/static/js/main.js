document.addEventListener('DOMContentLoaded', () => {
  // Navbar scroll effect
  const navbar = document.getElementById('navbar');
  if (navbar) {
    window.addEventListener('scroll', () => {
      navbar.classList.toggle('scrolled', window.scrollY > 20);
    });
  }

  // Role toggle for register
  window.setRole = function(role) {
    document.getElementById('roleInput').value = role;
    document.querySelectorAll('.role-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    const companyGrp = document.getElementById('companyGroup');
    const farmGrp    = document.getElementById('farmGroup');
    const skillsGrp  = document.getElementById('skillsGroup');
    if (companyGrp) companyGrp.style.display = role === 'farmer' ? 'block' : 'none';
    if (farmGrp)    farmGrp.style.display    = role === 'farmer' ? 'block' : 'none';
    if (skillsGrp)  skillsGrp.style.display  = role === 'consumer' ? 'block' : 'none';
  };

  // Star rating
  const stars = document.querySelectorAll('.star-label');
  stars.forEach((star, idx) => {
    star.addEventListener('click', () => {
      stars.forEach((s, i) => s.style.color = i <= idx ? '#F59E0B' : '#D1D5DB');
    });
  });

  // Auto-dismiss flash
  document.querySelectorAll('.flash').forEach(f => {
    setTimeout(() => { f.style.opacity='0'; f.style.transform='translateY(-10px)';
      setTimeout(() => f.remove(), 300); }, 4000);
  });
});
